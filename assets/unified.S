// Additional output adapter for the *same* captured OriginOS SurfaceFlinger.
// x0 = VivoLcmBrightnessController, w1 = unflagged panel DBV (w21 at call site).
// Reuse BC04's already tested Apollo inverse and standard persist queue.
.text
.global op13_unified_output
.type op13_unified_output,%function
op13_unified_output:
    .inst 0xd503245f
    mov w2, w1
field_unified_max:
    add x9, x0, #0x191
    ldr w1, [x9]
field_unified_manager:
    ldr x0, [x0, #0x78]
    cbz x0, .Lreturn
    b op13_existing_output
.Lreturn:
    ret
.size op13_unified_output, .-op13_unified_output
