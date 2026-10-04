// Parameterized audited A17 implementation + selected hardware Apollo table. Event-driven conversion, no I/O.
.text
.global op13_dbv_to_hal
.type op13_dbv_to_hal,%function
op13_dbv_to_hal:
    .inst 0xd503245f
    cmp w0, #0
    b.le .Loff
parameter_maximum:
    mov w10, #4094
    cmp w0, w10
    b.ge .Lmax
    // 16 entries per block: uint16 base, 15 four-bit positive deltas.
    adrp x9, op13_inverse_table
    add x9, x9, :lo12:op13_inverse_table
    lsr w10, w0, #4
    add x10, x10, x10, lsl #2
    add x9, x9, x10, lsl #1
    ldrh w10, [x9]
    ldur x11, [x9, #2]
    and w12, w0, #15
    cbz w12, .Ldecoded
.Lsum:
    and w13, w11, #15
    add w10, w10, w13
    lsr x11, x11, #4
    subs w12, w12, #1
    b.ne .Lsum
.Ldecoded:
    // Positive requests below the first reachable DBV retain minimum light.
    cmp w10, #1
    csinc w10, w10, wzr, ge
    sub w10, w10, #1
    ucvtf s0, w10
    // Apollo truncates (1 + normalized * 4673). Use an interior point of
    // the exact logical bin, avoiding float-rounding to the preceding level.
    fmov s2, #0.25
    fadd s0, s0, s2
parameter_logical_span:
    mov w10, #4673
    ucvtf s2, w10
    fdiv s0, s0, s2
    ret
.Loff:
    fmov s0, #-1.0
    ret
.Lmax:
    fmov s0, #1.0
    ret
.size op13_dbv_to_hal, .-op13_dbv_to_hal

.global op13_sdr_fallback
.type op13_sdr_fallback,%function
op13_sdr_fallback:
    .inst 0xd503245f
    // x19=DBM, x20=output parcel, s1=original SDR UI fraction.
    // This site is reached only when original HDR/sunlight handling declines.
field_sdr_enable:
    ldrb w9, [x19, #0x78]
    cbz w9, .Loriginal
field_sdr_hbm:
    ldr x9, [x19, #0xf0]
    cbz x9, .Loriginal
field_hbm_normal:
    ldr w9, [x9, #0xc4]
    cmp w9, #0
    b.le .Loriginal
parameter_maximum_sdr:
    mov w10, #4094
    cmp w9, w10
    b.gt .Loriginal
    fcmp s1, #0.0
    b.lt .Loriginal // includes unordered/NaN; preserve existing off sentinel
    fmov s2, #1.0
    fcmp s1, s2
    b.gt .Loriginal
    ucvtf s2, w9
    fmul s0, s1, s2
    fcvtzs w0, s0
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    bl op13_dbv_to_hal
field_sdr_output:
    str s0, [x20, #0x10]
    ldp x29, x30, [sp], #16
    ret
.Loriginal:
field_sdr_original:
    str s1, [x20, #0x10]
    ret
.size op13_sdr_fallback, .-op13_sdr_fallback

.global op13_hdr_output
.type op13_hdr_output,%function
op13_hdr_output:
    .inst 0xd503245f
    cbz x0, .Lreturn
    cmp w1, #0
    b.le .Lreturn
field_dbm_device:
    ldr x9, [x0, #8]
    cbz x9, .Lreturn
    cmp w2, w1
    csel w0, w1, w2, gt
    stp x9, x30, [sp, #-16]!
    bl op13_dbv_to_hal
    ldp x9, x30, [sp], #16
field_device_brightness:
    str s0, [x9, #0xa8]
    mov w10, #1
field_device_dirty:
    strb w10, [x9, #0xac]
    mov x0, x9
    mov w1, #1
    b op13_persist_brightness
.Lreturn:
    ret
.size op13_hdr_output, .-op13_hdr_output
