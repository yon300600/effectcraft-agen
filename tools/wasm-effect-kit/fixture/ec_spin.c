/*
 * ec_spin.c — a deliberately non-terminating fixture, used only to prove that the runtime's
 * execution limit (EffectCraft's wasmi fuel budget; the harness's wasmtime fuel) stops a
 * runaway plug-in instead of hanging the host.
 *
 * Not a production effect, not loaded by the app.
 */

#include <stdint.h>

#include "manifest_bytes_spin.h"

__attribute__((export_name("ec_api_version"))) int32_t ec_api_version(void) {
    return 1;
}

__attribute__((export_name("ec_manifest_ptr"))) int32_t ec_manifest_ptr(void) {
    return (int32_t)(uintptr_t)EC_MANIFEST;
}

__attribute__((export_name("ec_manifest_len"))) int32_t ec_manifest_len(void) {
    return (int32_t)EC_MANIFEST_LEN;
}

__attribute__((export_name("ec_alloc"))) int32_t ec_alloc(int32_t bytes) {
    (void)bytes;
    return 65536; /* a page the module reserves for the host's buffer */
}

__attribute__((export_name("ec_render"))) int32_t ec_render(int32_t pixels, int32_t width, int32_t height, int32_t params, int32_t nparams, double time, double scale) {
    (void)pixels;
    (void)width;
    (void)height;
    (void)params;
    (void)nparams;
    (void)time;
    (void)scale;
    /* A volatile counter, so the optimiser cannot prove the loop terminates and remove it. */
    static volatile uint64_t spin;
    for (;;) {
        spin = spin + 1u;
    }
}
