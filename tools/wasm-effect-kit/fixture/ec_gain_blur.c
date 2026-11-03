/*
 * ec_gain_blur.c — the EffectCraft WASM kit's ABI conformance fixture.
 *
 * THIS IS A TEST FIXTURE, NOT A PRODUCTION EFFECT, and not a reconstruction of any
 * third-party effect. Its only job is to prove, end to end, that a module compiled from
 * source runs through EffectCraft's plug-in API v1 in a real WebAssembly runtime:
 * module loading, memory growth, the parameter/pixel buffer, per-frame parameters,
 * deterministic pixel processing, output read-back and error codes.
 *
 * ABI (docs/plugins.md, "WebAssembly ABI (v1)"), no imports:
 *
 *   memory                            exported linear memory
 *   ec_api_version() -> i32           must return 1
 *   ec_manifest_ptr() -> i32          UTF-8 JSON manifest in memory
 *   ec_manifest_len() -> i32
 *   ec_alloc(bytes: i32) -> i32       8-byte-aligned buffer of at least `bytes` bytes
 *   ec_render(pixels: i32, width: i32, height: i32, params: i32, nparams: i32,
 *             time: f64, scale: f64) -> i32     0 = ok, non-zero = error code
 *
 * Layout of the buffer `ec_alloc` returns: `nparams` little-endian f64 parameter values,
 * immediately followed by `width * height` premultiplied RGBA pixels as little-endian f32
 * (row-major, no padding, 4 channels per pixel).
 *
 * The manifest is generated from fixture/plugin.json by build.sh (manifest_bytes.h), so the
 * module and the checked-in manifest file can never disagree.
 *
 * Determinism: all accumulation is f64 in a fixed order and the module is built with
 * -ffp-contract=off, so the same inputs give bit-identical f32 output in every runtime; the
 * harnesses compare against an independent reference implementation of the same math.
 */

#include <stddef.h>
#include <stdint.h>

#include "manifest_bytes.h"

/* Parameter order, as declared in plugin.json (flat f64 slots). */
enum {
    P_RADIUS = 0, /* slider, 0..64                                              */
    P_GAIN,       /* slider, 0..4                                               */
    P_TINT_R,     /* colour, 4 slots: r, g, b, a                                */
    P_TINT_G,
    P_TINT_B,
    P_TINT_A,
    P_MIX,      /* slider 0..100: how far to mix the tint in                  */
    P_MODE,     /* popup 0-based: 0 = blur and gain, 1 = invert alpha, 2 = none */
    P_ORIGIN_X, /* point, 2 slots, in buffer pixels (host maps it)            */
    P_ORIGIN_Y,
    P_ENABLE, /* checkbox, 0 or 1                                           */
    P_COUNT
};

/* Error codes returned by ec_render (0 = success, as the host documents). */
enum {
    EC_OK = 0,
    EC_TOO_FEW_PARAMS = 1, /* fewer parameters than the manifest declares   */
    EC_BAD_FRAME = 2,      /* null or non-positive width/height/pixels      */
    EC_BAD_POINTERS = 3,   /* a null params/pixels pointer                  */
    EC_BUFFER_TOO_SMALL = 4, /* the frame does not fit the ec_alloc buffer  */
    EC_NO_MEMORY = 5,      /* the module could not grow its memory          */
};

#define EC_PAGE 65536u
#define EC_ALIGN 8u

/* wasm-ld places the data segment (the manifest) at the bottom of linear memory and defines
 * __heap_base right after it: every byte above it is ours to grow into. */
extern unsigned char __heap_base;

static int32_t g_alloc_bytes; /* bytes the last successful ec_alloc handed out */

static uintptr_t heap_start(void) {
    uintptr_t base = (uintptr_t)&__heap_base;
    return (base + (uintptr_t)(EC_ALIGN - 1)) & ~(uintptr_t)(EC_ALIGN - 1);
}

/* Grow linear memory until it has at least `end` bytes; 0 = could not grow. */
static int ensure_end(uintptr_t end) {
    uintptr_t have = (uintptr_t)__builtin_wasm_memory_size(0) * (uintptr_t)EC_PAGE;
    if (have >= end) {
        return 1;
    }
    uintptr_t pages = (end - have + (uintptr_t)EC_PAGE - 1) / (uintptr_t)EC_PAGE;
    return __builtin_wasm_memory_grow(0, (size_t)pages) != (size_t)-1;
}

__attribute__((export_name("ec_api_version"))) int32_t ec_api_version(void) {
    return 1;
}

__attribute__((export_name("ec_manifest_ptr"))) int32_t ec_manifest_ptr(void) {
    return (int32_t)(uintptr_t)EC_MANIFEST;
}

__attribute__((export_name("ec_manifest_len"))) int32_t ec_manifest_len(void) {
    return (int32_t)EC_MANIFEST_LEN;
}

/* One reusable buffer for the parameters and the pixels (the host fills it, then reads it). */
__attribute__((export_name("ec_alloc"))) int32_t ec_alloc(int32_t bytes) {
    if (bytes < 0) {
        return 0;
    }
    uintptr_t base = heap_start();
    if (!ensure_end(base + (uintptr_t)bytes)) {
        g_alloc_bytes = 0;
        return 0;
    }
    g_alloc_bytes = bytes;
    return (int32_t)base;
}

static double clampd(double v, double lo, double hi) {
    if (v < lo) {
        return lo;
    }
    if (v > hi) {
        return hi;
    }
    return v;
}

static int32_t iround(double v) {
    return (int32_t)(v < 0.0 ? v - 0.5 : v + 0.5);
}

/*
 * Separable box blur over premultiplied RGBA, edge pixels clamped, accumulating left to right
 * in f64 so the result does not depend on the runtime's vectorisation choices.
 * `src` and `dst` hold width * height * 4 f64 values.
 */
static void box_blur(double *src, double *dst, int32_t w, int32_t h, int32_t radius) {
    /* Horizontal pass: src -> dst. */
    for (int32_t y = 0; y < h; y++) {
        const double *row = src + (size_t)y * (size_t)w * 4u;
        double *out = dst + (size_t)y * (size_t)w * 4u;
        for (int32_t x = 0; x < w; x++) {
            double acc[4] = {0.0, 0.0, 0.0, 0.0};
            double n = 0.0;
            for (int32_t k = -radius; k <= radius; k++) {
                int32_t sx = x + k;
                if (sx < 0) {
                    sx = 0;
                }
                if (sx >= w) {
                    sx = w - 1;
                }
                const double *p = row + (size_t)sx * 4u;
                acc[0] += p[0];
                acc[1] += p[1];
                acc[2] += p[2];
                acc[3] += p[3];
                n += 1.0;
            }
            double *q = out + (size_t)x * 4u;
            q[0] = acc[0] / n;
            q[1] = acc[1] / n;
            q[2] = acc[2] / n;
            q[3] = acc[3] / n;
        }
    }
    /* Vertical pass: dst -> src (back in place). */
    for (int32_t y = 0; y < h; y++) {
        for (int32_t x = 0; x < w; x++) {
            double acc[4] = {0.0, 0.0, 0.0, 0.0};
            double n = 0.0;
            for (int32_t k = -radius; k <= radius; k++) {
                int32_t sy = y + k;
                if (sy < 0) {
                    sy = 0;
                }
                if (sy >= h) {
                    sy = h - 1;
                }
                const double *p = dst + ((size_t)sy * (size_t)w + (size_t)x) * 4u;
                acc[0] += p[0];
                acc[1] += p[1];
                acc[2] += p[2];
                acc[3] += p[3];
                n += 1.0;
            }
            double *q = src + ((size_t)y * (size_t)w + (size_t)x) * 4u;
            q[0] = acc[0] / n;
            q[1] = acc[1] / n;
            q[2] = acc[2] / n;
            q[3] = acc[3] / n;
        }
    }
}

__attribute__((export_name("ec_render"))) int32_t ec_render(int32_t pixels, int32_t width, int32_t height, int32_t params, int32_t nparams, double time, double scale) {
    if (nparams < P_COUNT) {
        return EC_TOO_FEW_PARAMS;
    }
    if (pixels == 0 || params == 0) {
        return EC_BAD_POINTERS;
    }
    if (width <= 0 || height <= 0) {
        return EC_BAD_FRAME;
    }
    if (g_alloc_bytes <= 0) {
        return EC_BUFFER_TOO_SMALL; /* nothing was allocated for this frame */
    }
    const size_t count = (size_t)width * (size_t)height;
    const size_t need = (size_t)nparams * 8u + count * 16u;
    if (need > (size_t)g_alloc_bytes) {
        return EC_BUFFER_TOO_SMALL;
    }

    const double *p = (const double *)(uintptr_t)(uint32_t)params;
    float *px = (float *)(uintptr_t)(uint32_t)pixels;

    if (p[P_ENABLE] == 0.0 || iround(p[P_MODE]) == 2) {
        return EC_OK; /* pass through, unchanged */
    }

    if (iround(p[P_MODE]) == 1) {
        /* Invert alpha (premultiplied: keep colour/alpha ratio). */
        for (size_t i = 0; i < count; i++) {
            double r = (double)px[i * 4u + 0u];
            double g = (double)px[i * 4u + 1u];
            double b = (double)px[i * 4u + 2u];
            double a = clampd((double)px[i * 4u + 3u], 0.0, 1.0);
            double na = 1.0 - a;
            double k = a > 0.0 ? na / a : 0.0;
            px[i * 4u + 0u] = (float)(r * k);
            px[i * 4u + 1u] = (float)(g * k);
            px[i * 4u + 2u] = (float)(b * k);
            px[i * 4u + 3u] = (float)na;
        }
        return EC_OK;
    }

    /* mode 0: box blur, gain, tint. Radius follows the buffer resolution (`scale`). */
    int32_t radius = iround(clampd(p[P_RADIUS], 0.0, 64.0) * clampd(scale, 0.0, 8.0));
    if (radius > 64) {
        radius = 64;
    }

    /* f64 work area: `count * 4` for the image, plus the same again for the blur pass. */
    uintptr_t base = heap_start();
    uintptr_t work = base + (((uintptr_t)g_alloc_bytes + 15u) & ~(uintptr_t)15u);
    size_t work_bytes = count * 4u * sizeof(double);
    if (!ensure_end(work + work_bytes * 2u)) {
        return EC_NO_MEMORY;
    }
    double *img = (double *)work;
    double *tmp = (double *)(work + work_bytes);

    for (size_t i = 0; i < count * 4u; i++) {
        img[i] = (double)px[i];
    }
    if (radius > 0) {
        box_blur(img, tmp, width, height, radius);
    }

    double gain = clampd(p[P_GAIN], 0.0, 4.0);
    /* The host's `time` (layer seconds) reaches the module: a slow ramp over the first 4 s. */
    gain *= 1.0 + 0.25 * clampd(time, 0.0, 4.0);

    double mix = clampd(p[P_MIX], 0.0, 100.0) / 100.0;
    double tint[3] = {clampd(p[P_TINT_R], 0.0, 4.0), clampd(p[P_TINT_G], 0.0, 4.0), clampd(p[P_TINT_B], 0.0, 4.0)};
    double ox = (double)p[P_ORIGIN_X];
    double oy = (double)p[P_ORIGIN_Y];
    double half = 0.5 * (double)(width > height ? width : height);
    if (half <= 0.0) {
        half = 1.0;
    }

    for (int32_t y = 0; y < height; y++) {
        for (int32_t x = 0; x < width; x++) {
            size_t i = ((size_t)y * (size_t)width + (size_t)x) * 4u;
            double a = img[i + 3u];
            double c0 = img[i + 0u] * gain;
            double c1 = img[i + 1u] * gain;
            double c2 = img[i + 2u] * gain;
            if (mix > 0.0) {
                double dx = ((double)x + 0.5 - ox) / half;
                double dy = ((double)y + 0.5 - oy) / half;
                double d = __builtin_sqrt(dx * dx + dy * dy);
                double falloff = 1.0 - d;
                if (falloff < 0.0) {
                    falloff = 0.0;
                }
                double m = mix * falloff;
                double t0 = tint[0] * a;
                double t1 = tint[1] * a;
                double t2 = tint[2] * a;
                c0 = c0 * (1.0 - m) + t0 * m;
                c1 = c1 * (1.0 - m) + t1 * m;
                c2 = c2 * (1.0 - m) + t2 * m;
            }
            px[i + 0u] = (float)(c0 < 0.0 ? 0.0 : c0);
            px[i + 1u] = (float)(c1 < 0.0 ? 0.0 : c1);
            px[i + 2u] = (float)(c2 < 0.0 ? 0.0 : c2);
            px[i + 3u] = (float)clampd(a, 0.0, 1.0);
        }
    }
    return EC_OK;
}
