//! Real-host check for the WASM kit fixture: loads `fixture/ec_gain_blur.wasm` through
//! EffectCraft's own plug-in host (`effectcraft-plugin` → wasmi) and renders frames.
//!
//! This is the check that exercises the application's real runtime rather than a stand-in.
//! It needs a Rust toolchain and the workspace's dependencies (crates.io plus the pinned git
//! dependencies), so it is a standalone crate the workspace does not build; run it where cargo
//! works:
//!
//! ```sh
//! cd tools/wasm-effect-kit/host
//! cargo run --release
//! ```
//!
//! The sandbox in which the kit was built could not run it — no Rust toolchain, and egress to
//! the toolchain and registry hosts is blocked. `EFFECTCRAFT_WASM_TOOLCHAIN.md` records that,
//! and which of the kit's checks were actually executed.

use effectcraft_effects::plugin::{EffectPlugin, PluginFrame, PluginManifest, PluginParamKind, PluginParams};
use effectcraft_plugin::load_wasm;

/// The fixture module (kept in step with fixture/plugin.json by fixture/build.sh).
const WASM: &[u8] = include_bytes!("../../fixture/ec_gain_blur.wasm");

/// Default parameter values in declaration order, as the engine flattens them.
fn defaults(manifest: &PluginManifest) -> Vec<f64> {
    let mut out = Vec::new();
    for p in &manifest.params {
        match &p.kind {
            PluginParamKind::Slider { default, .. } => out.push(*default),
            PluginParamKind::Angle { default } => out.push(*default),
            PluginParamKind::Checkbox { default } => out.push(if *default { 1.0 } else { 0.0 }),
            PluginParamKind::Popup { default, .. } => out.push(*default as f64),
            PluginParamKind::Point { default } => out.extend_from_slice(default),
            PluginParamKind::Color { default } => out.extend_from_slice(default),
        }
    }
    out
}

fn render(plugin: &dyn EffectPlugin, manifest: &PluginManifest, flat: &[f64], pixels: &mut [[f32; 4]], width: u32, height: u32) -> Result<(), String> {
    let params = PluginParams { manifest, flat };
    let mut frame = PluginFrame { width, height, pixels, scale: 1.0 };
    plugin.render(&mut frame, &params, 0.0)
}

fn main() {
    let spec = match load_wasm(WASM, "tools/wasm-effect-kit/fixture/ec_gain_blur.wasm") {
        Ok(s) => s,
        Err(e) => {
            eprintln!("FAIL: the host refused the module: {e}");
            std::process::exit(1);
        }
    };
    println!("registered {} ({}), api 1, {} parameters", spec.id, spec.name, spec.params.len());
    assert_eq!(spec.id, "org.effectcraft.wasmkit.fixture.gain-blur");
    assert_eq!(spec.params.len(), 7);

    let plugin = match effectcraft_effects::plugin::plugin(spec.id) {
        Some(p) => p,
        None => {
            eprintln!("FAIL: the plug-in is not registered");
            std::process::exit(1);
        }
    };
    let manifest = plugin.manifest().clone();
    let mut flat = defaults(&manifest);
    assert_eq!(flat.len(), manifest.flat_len());

    // A 3x2 premultiplied RGBA frame in exact binary fractions.
    let (w, h) = (3u32, 2u32);
    let src: Vec<[f32; 4]> =
        vec![[0.25, 0.0, 0.5, 1.0], [0.5, 0.25, 0.0, 0.75], [0.0, 0.5, 0.25, 0.5], [0.75, 0.75, 0.75, 0.25], [0.125, 0.25, 0.5, 1.0], [1.0, 0.5, 0.0, 0.5]];

    // 1. Identity parameters (radius 0, gain 1, mix 0) leave the frame bit-identical.
    flat[0] = 0.0; // radius
    flat[1] = 1.0; // gain
    flat[6] = 0.0; // mix
    let mut pixels = src.clone();
    match render(plugin.as_ref(), &manifest, &flat, &mut pixels[..], w, h) {
        Ok(()) => println!("ok: identity parameters leave the frame unchanged"),
        Err(e) => {
            eprintln!("FAIL: identity render: {e}");
            std::process::exit(1);
        }
    }
    assert_eq!(pixels, src);

    // 2. Gain 2.0 doubles RGB and leaves alpha alone.
    flat[1] = 2.0;
    let mut pixels = src.clone();
    assert!(render(plugin.as_ref(), &manifest, &flat, &mut pixels[..], w, h).is_ok());
    for (out, inp) in pixels.iter().zip(src.iter()) {
        assert!((out[0] - 2.0 * inp[0]).abs() < 1e-6, "gain: {} vs {}", out[0], 2.0 * inp[0]);
        assert_eq!(out[3], inp[3], "gain changed alpha");
    }
    println!("ok: gain 2.0 doubles RGB, alpha untouched");

    // 3. A blur radius larger than 0 changes the frame.
    flat[0] = 2.0;
    flat[1] = 1.0;
    let mut pixels = src.clone();
    assert!(render(plugin.as_ref(), &manifest, &flat, &mut pixels[..], w, h).is_ok());
    assert_ne!(pixels, src, "radius 2 had no effect");
    println!("ok: radius 2 blurs the frame");

    // 4. Too few parameters: an error, and the frame is left as it was.
    let mut pixels = src.clone();
    let short = &flat[..3];
    let err = render(plugin.as_ref(), &manifest, short, &mut pixels[..], w, h);
    assert!(err.is_err(), "a short parameter list must fail");
    assert_eq!(pixels, src, "a failed render must leave the frame unchanged");
    println!("ok: a refused frame reports {:?} and leaves the pixels unchanged", err.err());

    println!("\nreal-host check passed (wasmi, plug-in API v1)");
}
