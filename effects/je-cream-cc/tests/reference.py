#!/usr/bin/env python3
"""An independent second implementation of the JE Cream CC reconstruction, in Python.

It exists to check the compiled module: same maths, written separately, in IEEE single precision
so the two can be compared exactly rather than approximately. Every operation is an np.float32
operation performed in the same order as the C code, so a difference is a real difference.

    from reference import render, defaults
    out = render(pixels_flat, w, h, params_flat)

pixels_flat: list of f32 values, premultiplied RGBA, row-major (the plug-in API v1 layout).
"""
import json
import pathlib

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
MANIFEST = json.loads((HERE.parent / "src" / "manifest.json").read_text())
SLOTS = {"slider": 1, "angle": 1, "checkbox": 1, "popup": 1, "point": 2, "color": 4}
F = np.float32


def defaults():
    """The manifest's defaults, flattened exactly like the host flattens them."""
    vals = []
    for p in MANIFEST["params"]:
        v = p["default"]
        if p["type"] == "checkbox":
            vals.append(1.0 if v else 0.0)
        elif p["type"] in ("color", "point"):
            vals += [float(x) for x in v]
        else:
            vals.append(float(v))
    return vals


def slot_of(pid):
    s = 0
    for p in MANIFEST["params"]:
        if p["id"] == pid:
            return s
        s += SLOTS[p["type"]]
    raise KeyError(pid)


def clamp01(v):
    return F(0.0) if v < 0 else (F(1.0) if v > 1 else v)


def luma709(r, g, b):
    return F(0.2126) * r + F(0.7152) * g + F(0.0722) * b


def px_scale(scale):
    """Buffer pixels per layer pixel (plug-in API v1: radii are layer pixels)."""
    return F(scale)


def radius_of(param_px, k):
    r = param_px * k
    if r <= F(0.5):
        return 0
    i = int(r + F(0.5))
    return 1 if i < 1 else i


def box_h(src, w, h, r):
    dst = np.zeros_like(src)
    inv = F(1.0) / F(2 * r + 1)
    for y in range(h):
        s = src[y * w:(y + 1) * w]
        ssum = F(0.0)
        for i in range(-r, r + 1):
            x = 0 if i < 0 else (w - 1 if i >= w else i)
            ssum = ssum + s[x]
        for x in range(w):
            dst[y * w + x] = ssum * inv
            add = x + r + 1
            sub = x - r
            add = w - 1 if add >= w else add
            sub = 0 if sub < 0 else sub
            ssum = ssum + (s[add] - s[sub])
    return dst


def box_v(src, w, h, r):
    dst = np.zeros_like(src)
    inv = F(1.0) / F(2 * r + 1)
    for x in range(w):
        ssum = F(0.0)
        for i in range(-r, r + 1):
            y = 0 if i < 0 else (h - 1 if i >= h else i)
            ssum = ssum + src[y * w + x]
        for y in range(h):
            dst[y * w + x] = ssum * inv
            add = y + r + 1
            sub = y - r
            add = h - 1 if add >= h else add
            sub = 0 if sub < 0 else sub
            ssum = ssum + (src[add * w + x] - src[sub * w + x])
    return dst


def blur_plane(p, w, h, r, passes):
    if r <= 0:
        return p.copy()
    rr = max(w, h) if r > w + h else r
    out = p.copy()
    for _ in range(passes):
        out = box_v(box_h(out, w, h, rr), w, h, rr)
    return out


def render(pix, w, h, params, scale=1.0):
    """pix: sequence of floats (premultiplied RGBA, row-major). Returns a list of floats."""
    P = lambda pid: F(params[slot_of(pid)])  # noqa: E731
    n = w * h
    rel = px_scale(scale)
    passes = 3 if int(P("quality")) == 0 else 1

    px = np.array(pix, dtype=np.float32)
    mix = P("mix")
    want_orig = mix < F(99.999)
    orig = px.copy()

    # straight colour
    for i in range(n):
        a = px[i * 4 + 3]
        if a > 0:
            inv = F(1.0) / a
            for c in range(3):
                px[i * 4 + c] = px[i * 4 + c] * inv
        else:
            for c in range(3):
                px[i * 4 + c] = F(0.0)

    # ---- stage 1: sharpening
    if P("sharpen_on") != F(0.0) and P("sharpen_amp") != F(0.0):
        sp = np.zeros(n, dtype=np.float32)
        for i in range(n):
            sp[i] = luma709(px[i * 4 + 0], px[i * 4 + 1], px[i * 4 + 2])
        t = max(P("edge_threshold"), F(0.0))
        mask = np.zeros(n, dtype=np.float32)
        for y in range(h):
            ym = y - 1 if y > 0 else 0
            yp = y + 1 if y + 1 < h else h - 1
            for x in range(w):
                xm = x - 1 if x > 0 else 0
                xp = x + 1 if x + 1 < w else w - 1
                tl, tc, tr = sp[ym * w + xm], sp[ym * w + x], sp[ym * w + xp]
                ml, mr = sp[y * w + xm], sp[y * w + xp]
                bl, bc, br = sp[yp * w + xm], sp[yp * w + x], sp[yp * w + xp]
                gx = (tr + F(2.0) * mr + br) - (tl + F(2.0) * ml + bl)
                gy = (bl + F(2.0) * bc + br) - (tl + F(2.0) * tc + tr)
                mag = (gx if gx >= 0 else -gx) + (gy if gy >= 0 else -gy)
                gn = mag * F(0.25)
                m = clamp01((gn - t) * F(4.0))
                mask[y * w + x] = m * m * (F(3.0) - F(2.0) * m)

        r_tiny = max(P("small_detail") * F(0.25), F(0.5)) * rel
        r_small = P("small_detail") * rel
        r_wide = P("sharpen_width") * rel
        if r_small < r_tiny:
            r_small = r_tiny
        if r_wide < r_small:
            r_wide = r_small
        lo, hi = F(0.0), r_wide
        m2 = r_small * r_small + (r_wide * r_wide - r_small * r_small) * F(0.5)
        for _ in range(24):
            mid = F(0.5) * (lo + hi)
            if mid * mid < m2:
                lo = mid
            else:
                hi = mid
        r_med = F(0.5) * (lo + hi)

        def sqrt_gap(a):
            lo2, hi2 = F(0.0), r_wide
            a = a if a > 0 else F(0.0)
            for _ in range(24):
                mid = F(0.5) * (lo2 + hi2)
                if mid * mid < a:
                    lo2 = mid
                else:
                    hi2 = mid
            return F(0.5) * (lo2 + hi2)

        R1 = radius_of(r_tiny, F(1.0))
        R2 = radius_of(sqrt_gap(r_small * r_small - r_tiny * r_tiny), F(1.0))
        R3 = radius_of(sqrt_gap(r_med * r_med - r_small * r_small), F(1.0))
        R4 = radius_of(sqrt_gap(r_wide * r_wide - r_med * r_med), F(1.0))

        det = np.zeros(3 * n, dtype=np.float32)
        for c in range(3):
            sq = np.array([px[i * 4 + c] for i in range(n)], dtype=np.float32)
            sp = sq.copy()
            sp = blur_plane(sp, w, h, R1, passes)
            det[c * n:(c + 1) * n] = F(3.0) * (sq - sp)
            sq = sp.copy()
            sp = blur_plane(sp, w, h, R2, passes)
            det[c * n:(c + 1) * n] += F(1.5) * (sq - sp)
            sq = sp.copy()
            sp = blur_plane(sp, w, h, R3, passes)
            det[c * n:(c + 1) * n] += F(1.0) * (sq - sp)
            sq = sp.copy()
            sp = blur_plane(sp, w, h, R4, passes)
            det[c * n:(c + 1) * n] += F(2.0) * (sq - sp)

        gains = [P("sharpen_r"), P("sharpen_g"), P("sharpen_b")]
        for i in range(n):
            d = [det[c * n + i] for c in range(3)]
            l = luma709(d[0], d[1], d[2])
            m = mask[i] * P("sharpen_amp")
            for c in range(3):
                v = P("sharpen_luma") * l + P("sharpen_chroma") * (d[c] - l)
                px[i * 4 + c] = px[i * 4 + c] + m * v * gains[c]

    # ---- stage 2: unsharp mask
    if P("unsharp_on") != F(0.0) and P("unsharp_amount") != F(0.0):
        r = radius_of(P("unsharp_radius"), rel)
        amount = P("unsharp_amount") * F(0.01)
        thr = P("unsharp_threshold") / F(255.0)
        mixu = P("unsharp_mix") * F(0.01)
        for c in range(3):
            sq = np.array([px[i * 4 + c] for i in range(n)], dtype=np.float32)
            sp = blur_plane(sq.copy(), w, h, r, passes)
            d = sq - sp
            for i in range(n):
                if thr > 0:
                    ad = d[i] if d[i] >= 0 else -d[i]
                    if ad <= thr:
                        d[i] = F(0.0)
            flick = int(P("flicker"))
            if flick > 0:
                a, b, cc = F(0.25), F(0.5), F(0.25)
                if flick == 2:
                    a, b, cc = F(2.0) / F(7.0), F(3.0) / F(7.0), F(2.0) / F(7.0)
                if flick == 3:
                    a, b, cc = F(1.0) / F(3.0), F(1.0) / F(3.0), F(1.0) / F(3.0)
                sm = np.zeros(n, dtype=np.float32)
                for y in range(h):
                    ym = y - 1 if y > 0 else 0
                    yp = y + 1 if y + 1 < h else h - 1
                    for x in range(w):
                        sm[y * w + x] = a * d[ym * w + x] + b * d[y * w + x] + cc * d[yp * w + x]
                d = sm
            for i in range(n):
                out = sq[i] + amount * d[i]
                if mixu > 0:
                    out = out + mixu * (sq[i] - out)
                elif mixu < 0:
                    out = out - (-mixu) * sq[i]
                px[i * 4 + c] = out

    # ---- stages 4 and 5: glows
    for gi in (0, 1):
        pre = "glow1_" if gi == 0 else "glow2_"
        if P(pre + "on") == F(0.0) or P(pre + "brightness") == F(0.0):
            continue
        thr = P(pre + "threshold")
        det = np.zeros(3 * n, dtype=np.float32)
        any_energy = False
        for i in range(n):
            r_, g_, b_ = px[i * 4 + 0], px[i * 4 + 1], px[i * 4 + 2]
            y = luma709(r_, g_, b_)
            e = y - thr
            if e <= 0:
                continue
            any_energy = True
            f = e / max(y, F(1e-6))
            det[i] = r_ * f
            det[n + i] = g_ * f
            det[2 * n + i] = b_ * f
        halo = F(0.0)
        if any_energy:
            ws = [P(pre + "width") * P(pre + "width_r"), P(pre + "width") * P(pre + "width_g"),
                  P(pre + "width") * P(pre + "width_b")]
            for c in range(3):
                rr = max(ws[c], F(0.0)) * rel
                det[c * n:(c + 1) * n] = blur_plane(det[c * n:(c + 1) * n].copy(), w, h,
                                                    radius_of(rr, F(1.0)), passes)
            br = P(pre + "brightness")
            col = [F(params[slot_of(pre + "color") + c]) for c in range(3)]
            comb = int(P(pre + "combine"))
            for i in range(n):
                g = [br * det[c * n + i] * col[c] for c in range(3)]
                m = max(g[0], g[1], g[2])
                if m > halo:
                    halo = m
                for c in range(3):
                    s = px[i * 4 + c]
                    if comb == 0:
                        o = s * g[c]
                    elif comb == 1:
                        o = s + g[c]
                    elif comb == 2:
                        o = F(1.0) - (F(1.0) - s) * (F(1.0) - g[c])
                    elif comb == 3:
                        o = s - g[c]
                    else:
                        o = F(2.0) * s * g[c] if s < F(0.5) else F(1.0) - F(2.0) * (F(1.0) - s) * (F(1.0) - g[c])
                    px[i * 4 + c] = o
        if P(pre + "affect_alpha") > F(0.0) and halo > F(0.0):
            a = P(pre + "affect_alpha")
            for i in range(n):
                al = px[i * 4 + 3]
                px[i * 4 + 3] = clamp01(al + a * (F(1.0) - al) * clamp01(halo))

    # ---- premultiply, then mix
    for i in range(n):
        a = px[i * 4 + 3]
        for c in range(3):
            px[i * 4 + c] = px[i * 4 + c] * a
    if want_orig:
        m = clamp01(mix * F(0.01))
        for i in range(4 * n):
            px[i] = orig[i] + (px[i] - orig[i]) * m

    return [float(v) for v in px]
