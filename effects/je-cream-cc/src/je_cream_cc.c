// JE Cream CC (reconstructed) — EffectCraft plug-in API v1 module.
//
// Independent reconstruction of the *settings* stored in the preset "JE Cream CC"
// (S_Sharpen -> BCC Unsharp Mask -> Looks -> S_Glow -> S_Glow 2). None of the proprietary
// plug-ins' code, binaries or formats were read: the maths below are our own implementations of
// publicly documented techniques (multi-band unsharp sharpening, unsharp masking, thresholded
// bloom). See ../ANALYSIS.md for the parameter inventory and ../README.md for what is exact,
// approximate and unsupported.
//
// Built freestanding for wasm32 (no libc, no imports). Determinism: fixed loop order, f32
// arithmetic only, no FMA contraction (-ffp-contract=off), no clocks or randomness.

#include <stdint.h>

#include "manifest_bytes.h"
#include "param_index.h"

// ---------------------------------------------------------------- exports and memory

#define EXPORT(name) __attribute__((export_name(#name)))

// wasm-ld marks the first address after all static data; the host's buffer and our scratch
// arena start there, so nothing is placed over the compiled-in manifest.
extern unsigned char __heap_base;

static unsigned char *g_buf = 0;      // the buffer ec_alloc hands out (params + pixels)
static uintptr_t g_buf_bytes = 0;     // its length
static unsigned char *g_scratch = 0;  // scratch arena, laid out after g_buf
static uintptr_t g_scratch_bytes = 0;

static uintptr_t heap_end(void) { return (uintptr_t)__builtin_wasm_memory_size(0) * 65536u; }

static int ensure_heap(uintptr_t want) {
    uintptr_t end = heap_end();
    if (end >= want) return 1;
    uintptr_t need = want - end;
    uintptr_t pages = (need + 65535u) / 65536u;
    if (__builtin_wasm_memory_grow(0, pages) == (uintptr_t)-1) return 0;
    return 1;
}

EXPORT(ec_api_version) int ec_api_version(void) { return 1; }
EXPORT(ec_manifest_ptr) const unsigned char *ec_manifest_ptr(void) { return EC_MANIFEST; }
EXPORT(ec_manifest_len) int ec_manifest_len(void) { return EC_MANIFEST_LEN; }

EXPORT(ec_alloc) void *ec_alloc(int bytes) {
    if (bytes <= 0) return 0;
    if (!g_buf) g_buf = &__heap_base;
    uintptr_t need = (uintptr_t)bytes;
    if (need > g_buf_bytes) {
        if (!ensure_heap((uintptr_t)g_buf + need)) return 0;
        g_buf_bytes = need;
    }
    return g_buf;
}

// ---------------------------------------------------------------- small helpers

static float clamp01(float v) { return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v); }

static float maxf(float a, float b) { return a > b ? a : b; }

static float luma709(float r, float g, float b) { return 0.2126f * r + 0.7152f * g + 0.0722f * b; }

// Radii are layer pixels (the preset was authored at 1920 px), and the host may hand us a
// preview buffer at `scale` buffer pixels per layer pixel, so multiply by it (plug-in API v1).

static int radius_of(float param_px, float k) {
    float r = param_px * k;
    if (r <= 0.5f) return 0;
    int i = (int)(r + 0.5f);
    return i < 1 ? 1 : i;
}

// ---------------------------------------------------------------- box blur (3 passes = Gaussian-ish)

// Horizontal box average with replicated edges: deterministic, O(1) per pixel.
static void box_h(const float *src, float *dst, int w, int h, int r) {
    float inv = 1.0f / (float)(2 * r + 1);
    for (int y = 0; y < h; y++) {
        const float *s = src + (long)y * w;
        float *d = dst + (long)y * w;
        float sum = 0.0f;
        for (int i = -r; i <= r; i++) {
            int x = i < 0 ? 0 : (i >= w ? w - 1 : i);
            sum += s[x];
        }
        for (int x = 0; x < w; x++) {
            d[x] = sum * inv;
            int add = x + r + 1;
            int sub = x - r;
            add = add >= w ? w - 1 : add;
            sub = sub < 0 ? 0 : sub;
            sum += s[add] - s[sub];
        }
    }
}

static void box_v(const float *src, float *dst, int w, int h, int r) {
    float inv = 1.0f / (float)(2 * r + 1);
    for (int x = 0; x < w; x++) {
        float sum = 0.0f;
        for (int i = -r; i <= r; i++) {
            int y = i < 0 ? 0 : (i >= h ? h - 1 : i);
            sum += src[(long)y * w + x];
        }
        for (int y = 0; y < h; y++) {
            dst[(long)y * w + x] = sum * inv;
            int add = y + r + 1;
            int sub = y - r;
            add = add >= h ? h - 1 : add;
            sub = sub < 0 ? 0 : sub;
            sum += src[(long)add * w + x] - src[(long)sub * w + x];
        }
    }
}

// Blur a single plane in place; `tmp` is scratch of w*h floats. passes = 3 (Best) or 1 (Fast).
static void blur_plane(float *p, float *tmp, int w, int h, int r, int passes) {
    if (r <= 0) return;
    int rr = r > (w + h) ? (w > h ? w : h) : r;  // a radius wider than the frame adds nothing
    for (int i = 0; i < passes; i++) {
        box_h(p, tmp, w, h, rr);
        box_v(tmp, p, w, h, rr);
    }
}

// ---------------------------------------------------------------- main entry

typedef struct {
    float mix;
    int sharpen_on;
    float sharpen_amp, edge_threshold, small_detail, sharpen_width;
    float sharpen_luma, sharpen_chroma, sharpen_r, sharpen_g, sharpen_b;
    int quality;
    int unsharp_on;
    float unsharp_radius, unsharp_amount, unsharp_threshold, unsharp_mix;
    int flicker;
    float looks_strength;
    int glow_on[2];
    float glow_bright[2], glow_thresh[2], glow_width[2];
    float glow_wr[2], glow_wg[2], glow_wb[2];
    float glow_color[2][3];
    int glow_combine[2];
    float glow_alpha[2];
} Params;

static float P(const double *p, int i) { return (float)p[i]; }

EXPORT(ec_render) int ec_render(float *pixels, int w, int h, const double *params, int nparams,
                                double time, double scale) {
    (void)time;
    if (!pixels || !params) return 3;
    if (nparams < EC_NPARAMS) return 1;
    if (w <= 0 || h <= 0) return 2;

    Params q;
    q.mix = P(params, EC_MIX);
    q.sharpen_on = P(params, EC_SHARPEN_ON) != 0.0f;
    q.sharpen_amp = P(params, EC_SHARPEN_AMP);
    q.edge_threshold = P(params, EC_EDGE_THRESHOLD);
    q.small_detail = P(params, EC_SMALL_DETAIL);
    q.sharpen_width = P(params, EC_SHARPEN_WIDTH);
    q.sharpen_luma = P(params, EC_SHARPEN_LUMA);
    q.sharpen_chroma = P(params, EC_SHARPEN_CHROMA);
    q.sharpen_r = P(params, EC_SHARPEN_R);
    q.sharpen_g = P(params, EC_SHARPEN_G);
    q.sharpen_b = P(params, EC_SHARPEN_B);
    q.quality = (int)P(params, EC_QUALITY);
    q.unsharp_on = P(params, EC_UNSHARP_ON) != 0.0f;
    q.unsharp_radius = P(params, EC_UNSHARP_RADIUS);
    q.unsharp_amount = P(params, EC_UNSHARP_AMOUNT);
    q.unsharp_threshold = P(params, EC_UNSHARP_THRESHOLD);
    q.unsharp_mix = P(params, EC_UNSHARP_MIX);
    q.flicker = (int)P(params, EC_FLICKER);
    q.looks_strength = P(params, EC_LOOKS_STRENGTH);
    for (int k = 0; k < 2; k++) {
        int base = k == 0 ? 0 : 1;
        q.glow_on[k] = P(params, base ? EC_GLOW2_ON : EC_GLOW1_ON) != 0.0f;
        q.glow_bright[k] = P(params, base ? EC_GLOW2_BRIGHTNESS : EC_GLOW1_BRIGHTNESS);
        q.glow_thresh[k] = P(params, base ? EC_GLOW2_THRESHOLD : EC_GLOW1_THRESHOLD);
        q.glow_width[k] = P(params, base ? EC_GLOW2_WIDTH : EC_GLOW1_WIDTH);
        q.glow_wr[k] = P(params, base ? EC_GLOW2_WIDTH_R : EC_GLOW1_WIDTH_R);
        q.glow_wg[k] = P(params, base ? EC_GLOW2_WIDTH_G : EC_GLOW1_WIDTH_G);
        q.glow_wb[k] = P(params, base ? EC_GLOW2_WIDTH_B : EC_GLOW1_WIDTH_B);
        int cbase = base ? EC_GLOW2_COLOR : EC_GLOW1_COLOR;
        q.glow_color[k][0] = P(params, cbase + 0);
        q.glow_color[k][1] = P(params, cbase + 1);
        q.glow_color[k][2] = P(params, cbase + 2);
        q.glow_combine[k] = (int)P(params, base ? EC_GLOW2_COMBINE : EC_GLOW1_COMBINE);
        q.glow_alpha[k] = P(params, base ? EC_GLOW2_AFFECT_ALPHA : EC_GLOW1_AFFECT_ALPHA);
    }

    const long n = (long)w * (long)h;
    const int passes = q.quality == 0 ? 3 : 1;
    const float k = (float)scale;

    // Scratch: P, Q, TMP, DET (3 planes), MASK, plus the original frame when mixing.
    long need = 0;
    float *sp = 0, *sq = 0, *stmp = 0, *sdet = 0, *smask = 0;
    float *sorig = 0;
    int want_orig = q.mix < 99.999f;
    {
        uintptr_t base = (uintptr_t)g_buf + g_buf_bytes;
        base = (base + 15u) & ~(uintptr_t)15u;
        // P, Q, TMP (3n) + DET (3n) + MASK (n) + the original frame (4n when mixing)
        long floats = 3 * n + 3 * n + n;
        if (want_orig) floats += 4 * n;
        long bytes = floats * 4;
        if (!ensure_heap(base + bytes)) return 5;
        sp = (float *)base;
        sq = sp + n;
        stmp = sq + n;
        sdet = stmp + n;
        smask = sdet + 3 * n;
        sorig = want_orig ? smask + n : 0;
        need = bytes;
    }
    (void)need;

    // Keep the original frame (premultiplied) for the final mix, then work in straight RGBA.
    if (sorig) {
        for (long i = 0; i < 4 * n; i++) sorig[i] = pixels[i];
    }
    for (long i = 0; i < n; i++) {
        float a = pixels[i * 4 + 3];
        if (a > 0.0f) {
            float inv = 1.0f / a;
            pixels[i * 4 + 0] *= inv;
            pixels[i * 4 + 1] *= inv;
            pixels[i * 4 + 2] *= inv;
        } else {
            pixels[i * 4 + 0] = 0.0f;
            pixels[i * 4 + 1] = 0.0f;
            pixels[i * 4 + 2] = 0.0f;
        }
    }

    // ---- stage 1: multi-band sharpening -------------------------------------------------
    if (q.sharpen_on && q.sharpen_amp != 0.0f) {
        // Luma plane (for the edge mask) from the straight colour.
        for (long i = 0; i < n; i++)
            sp[i] = luma709(pixels[i * 4 + 0], pixels[i * 4 + 1], pixels[i * 4 + 2]);

        // Edge mask: Sobel slope of luma, normalised by 4 (the slope of a full 0..1 step),
        // then a smooth ramp of width 0.25 starting at the preset's Edge Threshold.
        {
            float t = q.edge_threshold < 0.0f ? 0.0f : q.edge_threshold;
            for (int y = 0; y < h; y++) {
                int ym = y > 0 ? y - 1 : 0, yp = y + 1 < h ? y + 1 : h - 1;
                for (int x = 0; x < w; x++) {
                    int xm = x > 0 ? x - 1 : 0, xp = x + 1 < w ? x + 1 : w - 1;
                    float tl = sp[(long)ym * w + xm], tc = sp[(long)ym * w + x], tr = sp[(long)ym * w + xp];
                    float ml = sp[(long)y * w + xm], mr = sp[(long)y * w + xp];
                    float bl = sp[(long)yp * w + xm], bc = sp[(long)yp * w + x], br = sp[(long)yp * w + xp];
                    float gx = (tr + 2.0f * mr + br) - (tl + 2.0f * ml + bl);
                    float gy = (bl + 2.0f * bc + br) - (tl + 2.0f * tc + tr);
                    float mag = (gx < 0.0f ? -gx : gx) + (gy < 0.0f ? -gy : gy);
                    float gn = mag * 0.25f;  // |gx|+|gy| of a 0..1 step is 4
                    float m = (gn - t) * 4.0f;  // ramp over 0.25
                    m = clamp01(m);
                    smask[(long)y * w + x] = m * m * (3.0f - 2.0f * m);
                }
            }
        }

        // Band radii: Small Detail Size is the finest band, Sharpen Width the widest. The four
        // bands are incremental blurs, so their variances add to the widest radius.
        float r_tiny = maxf(q.small_detail * 0.25f, 0.5f) * k;
        float r_small = q.small_detail * k;
        float r_wide = q.sharpen_width * k;
        if (r_small < r_tiny) r_small = r_tiny;
        if (r_wide < r_small) r_wide = r_small;
        float r_med = 0.0f;
        {
            float m2 = r_small * r_small + (r_wide * r_wide - r_small * r_small) * 0.5f;
            r_med = 0.0f;
            float lo = 0.0f, hi = r_wide;
            for (int i = 0; i < 24; i++) {  // sqrt by bisection keeps the maths libc-free
                float mid = 0.5f * (lo + hi);
                if (mid * mid < m2) lo = mid; else hi = mid;
            }
            r_med = 0.5f * (lo + hi);
        }
        float d1 = r_tiny;
        float d2 = 0.0f, d3 = 0.0f, d4 = 0.0f;
        {
            float a = r_small * r_small - r_tiny * r_tiny;
            float b = r_med * r_med - r_small * r_small;
            float c = r_wide * r_wide - r_med * r_med;
            float lo = 0.0f, hi = r_wide;
            for (int i = 0; i < 24; i++) { float mid = 0.5f * (lo + hi); if (mid * mid < (a > 0 ? a : 0)) lo = mid; else hi = mid; }
            d2 = 0.5f * (lo + hi);
            lo = 0.0f; hi = r_wide;
            for (int i = 0; i < 24; i++) { float mid = 0.5f * (lo + hi); if (mid * mid < (b > 0 ? b : 0)) lo = mid; else hi = mid; }
            d3 = 0.5f * (lo + hi);
            lo = 0.0f; hi = r_wide;
            for (int i = 0; i < 24; i++) { float mid = 0.5f * (lo + hi); if (mid * mid < (c > 0 ? c : 0)) lo = mid; else hi = mid; }
            d4 = 0.5f * (lo + hi);
        }
        const int R1 = radius_of(d1, 1.0f), R2 = radius_of(d2, 1.0f), R3 = radius_of(d3, 1.0f), R4 = radius_of(d4, 1.0f);
        // Scale Tiny/Small/Medium/Large Details, at their documented defaults.
        const float w1 = 3.0f, w2 = 1.5f, w3 = 1.0f, w4 = 2.0f;

        for (int c = 0; c < 3; c++) {
            for (long i = 0; i < n; i++) sq[i] = pixels[i * 4 + c];
            // G1 = blur(I); band0 = I - G1
            for (long i = 0; i < n; i++) sp[i] = sq[i];
            blur_plane(sp, stmp, w, h, R1, passes);
            for (long i = 0; i < n; i++) sdet[c * n + i] = w1 * (sq[i] - sp[i]);
            // G2 = blur(G1); band1 = G1 - G2
            for (long i = 0; i < n; i++) sq[i] = sp[i];
            blur_plane(sp, stmp, w, h, R2, passes);
            for (long i = 0; i < n; i++) sdet[c * n + i] += w2 * (sq[i] - sp[i]);
            // G3 = blur(G2); band2 = G2 - G3
            for (long i = 0; i < n; i++) sq[i] = sp[i];
            blur_plane(sp, stmp, w, h, R3, passes);
            for (long i = 0; i < n; i++) sdet[c * n + i] += w3 * (sq[i] - sp[i]);
            // G4 = blur(G3); band3 = G3 - G4
            for (long i = 0; i < n; i++) sq[i] = sp[i];
            blur_plane(sp, stmp, w, h, R4, passes);
            for (long i = 0; i < n; i++) sdet[c * n + i] += w4 * (sq[i] - sp[i]);
        }

        float gr[3] = {q.sharpen_r, q.sharpen_g, q.sharpen_b};
        for (long i = 0; i < n; i++) {
            float dr = sdet[0 * n + i], dg = sdet[1 * n + i], db = sdet[2 * n + i];
            float l = luma709(dr, dg, db);
            float m = smask[i] * q.sharpen_amp;
            float d[3] = {dr, dg, db};
            for (int c = 0; c < 3; c++) {
                float v = q.sharpen_luma * l + q.sharpen_chroma * (d[c] - l);
                pixels[i * 4 + c] += m * v * gr[c];
            }
        }
    }

    // ---- stage 2: unsharp mask ----------------------------------------------------------
    if (q.unsharp_on && q.unsharp_amount != 0.0f) {
        int r = radius_of(q.unsharp_radius, k);
        float amount = q.unsharp_amount * 0.01f;
        float thr = q.unsharp_threshold / 255.0f;
        for (int c = 0; c < 3; c++) {
            for (long i = 0; i < n; i++) sq[i] = pixels[i * 4 + c];
            for (long i = 0; i < n; i++) sp[i] = sq[i];
            blur_plane(sp, stmp, w, h, r, passes);
            for (long i = 0; i < n; i++) {
                float d = sq[i] - sp[i];
                if (thr > 0.0f) {
                    float ad = d < 0.0f ? -d : d;
                    if (ad <= thr) d = 0.0f;
                }
                sdet[i] = d;  // detail, before the flicker filter
            }
            // Reduce Flicker: a vertical smoothing of the detail signal (1-2-1 / 2-3-2 / 1-1-1).
            if (q.flicker > 0) {
                float a = 0.25f, b = 0.5f, cc = 0.25f;
                if (q.flicker == 2) { a = 2.0f / 7.0f; b = 3.0f / 7.0f; cc = 2.0f / 7.0f; }
                if (q.flicker == 3) { a = 1.0f / 3.0f; b = 1.0f / 3.0f; cc = 1.0f / 3.0f; }
                for (int y = 0; y < h; y++) {
                    int ym = y > 0 ? y - 1 : 0, yp = y + 1 < h ? y + 1 : h - 1;
                    for (int x = 0; x < w; x++)
                        smask[(long)y * w + x] = a * sdet[(long)ym * w + x] + b * sdet[(long)y * w + x] +
                                                 cc * sdet[(long)yp * w + x];
                }
                for (long i = 0; i < n; i++) sdet[i] = smask[i];
            }
            float mix = q.unsharp_mix * 0.01f;
            for (long i = 0; i < n; i++) {
                float out = sq[i] + amount * sdet[i];
                if (mix > 0.0f) out += mix * (sq[i] - out);
                else if (mix < 0.0f) out -= (-mix) * sq[i];
                pixels[i * 4 + c] = out;
            }
        }
    }

    // ---- stage 3: Looks (Magic Bullet) ---------------------------------------------------
    // The preset's look payload is proprietary binary data (68,321 bytes, "MBL2") and is not
    // interpreted anywhere in this project, so the grade cannot be reproduced. The stage is a
    // documented no-op; `looks_strength` is exposed for completeness and does nothing.
    (void)q.looks_strength;

    // ---- stages 4 and 5: glows -----------------------------------------------------------
    for (int gi = 0; gi < 2; gi++) {
        if (!q.glow_on[gi] || q.glow_bright[gi] == 0.0f) continue;
        float thr = q.glow_thresh[gi];
        // Bright pass: energy above the threshold, carried at the pixel's own colour.
        int any = 0;
        for (long i = 0; i < n; i++) {
            float r = pixels[i * 4 + 0], g = pixels[i * 4 + 1], b = pixels[i * 4 + 2];
            float y = luma709(r, g, b);
            float e = y - thr;
            if (e <= 0.0f) {
                sdet[i] = 0.0f;
                sdet[n + i] = 0.0f;
                sdet[2 * n + i] = 0.0f;
                continue;
            }
            any = 1;
            float f = e / maxf(y, 1e-6f);
            sdet[i] = r * f;
            sdet[n + i] = g * f;
            sdet[2 * n + i] = b * f;
        }
        float halo = 0.0f;
        if (any) {
            float wr = maxf(q.glow_width[gi] * q.glow_wr[gi], 0.0f) * k;
            float wg = maxf(q.glow_width[gi] * q.glow_wg[gi], 0.0f) * k;
            float wb = maxf(q.glow_width[gi] * q.glow_wb[gi], 0.0f) * k;
            float rad[3] = {wr, wg, wb};
            for (int c = 0; c < 3; c++) {
                for (long i = 0; i < n; i++) sp[i] = sdet[c * n + i];
                blur_plane(sp, stmp, w, h, radius_of(rad[c], 1.0f), passes);
                for (long i = 0; i < n; i++) sdet[c * n + i] = sp[i];
            }
            float br = q.glow_bright[gi];
            float cr[3] = {q.glow_color[gi][0], q.glow_color[gi][1], q.glow_color[gi][2]};
            for (long i = 0; i < n; i++) {
                float g[3];
                for (int c = 0; c < 3; c++) g[c] = br * sdet[c * n + i] * cr[c];
                float m = maxf(maxf(g[0], g[1]), g[2]);
                if (m > halo) halo = m;
                for (int c = 0; c < 3; c++) {
                    float s = pixels[i * 4 + c];
                    float o = s;
                    switch (q.glow_combine[gi]) {
                        case 0: o = s * g[c]; break;                       // Mult
                        case 1: o = s + g[c]; break;                       // Add
                        case 2: o = 1.0f - (1.0f - s) * (1.0f - g[c]); break;  // Screen
                        case 3: o = s - g[c]; break;                       // Difference
                        default: {                                          // Overlay
                            o = s < 0.5f ? 2.0f * s * g[c] : 1.0f - 2.0f * (1.0f - s) * (1.0f - g[c]);
                            break;
                        }
                    }
                    pixels[i * 4 + c] = o;
                }
            }
        }
        if (q.glow_alpha[gi] > 0.0f && halo > 0.0f) {
            float a = q.glow_alpha[gi];
            for (long i = 0; i < n; i++) {
                float al = pixels[i * 4 + 3];
                pixels[i * 4 + 3] = clamp01(al + a * (1.0f - al) * clamp01(halo));
            }
        }
    }

    // ---- back to premultiplied RGB, then the preset's own mix ----------------------------
    for (long i = 0; i < n; i++) {
        float a = pixels[i * 4 + 3];
        pixels[i * 4 + 0] *= a;
        pixels[i * 4 + 1] *= a;
        pixels[i * 4 + 2] *= a;
    }
    if (sorig) {
        float m = clamp01(q.mix * 0.01f);
        for (long i = 0; i < 4 * n; i++) pixels[i] = sorig[i] + (pixels[i] - sorig[i]) * m;
    }
    return 0;
}
