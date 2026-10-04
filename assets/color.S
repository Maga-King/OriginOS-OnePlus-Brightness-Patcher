// Audited Vivo Android 17 binary only. Runs on profile construction, not polling.
.text
.global op13_collect_p3_intents
.type op13_collect_p3_intents,%function
op13_collect_p3_intents:
    stp x21, x22, [sp, #-32]!
    stp x23, x30, [sp, #16]
field_color_savedmap:
    ldr x8, [sp, #0x48] // caller's saved input map at original sp+0x28
    ldr x8, [x8, #0x10] // libc++ unordered_map first node
1:
    cbz x8, 4f
    ldr w9, [x8, #0x10] // ColorMode key
    cmp w9, #9 // only DISPLAY_P3; SRGB collection remains original
    b.eq 2f
    ldr x8, [x8]
    b 1b
2:
    ldp x22, x23, [x8, #0x18] // vector begin/end
field_color_intentset:
    add x21, sp, #0x80 // original candidate-intent set at caller sp+0x60
3:
    cmp x22, x23
    b.eq 4f
    mov x0, x21
    mov x1, x22
    mov x2, x22
    bl op13_original_insert_intent
    add x22, x22, #4
    b 3b
4:
    ldp x23, x30, [sp, #16]
    ldp x21, x22, [sp], #32
field_color_displaced:
    ldr x8, [sp, #0x70] // displaced instruction
    ret
.size op13_collect_p3_intents, .-op13_collect_p3_intents

.global op13_has_render_intent
.type op13_has_render_intent,%function
op13_has_render_intent:
    .inst 0xd503233f // paciasp; entered from BTI-compatible original function
    stp x29, x30, [sp, #-48]!
    stp x19, x20, [sp, #16]
    mov x29, sp
field_color_map:
    add x19, x0, #0x40
    mov w20, w1
    mov x8, #0x0881000000000000 // SRGB key, original semantics first
    orr x8, x8, x20
    str x8, [sp, #32]
    mov x0, x19
    add x1, sp, #32
    bl op13_original_find_mode
    cbz x0, 5f
    ldr w8, [x0, #0x20]
    cmp w8, w20
    b.eq 6f
5:
    mov x8, #0x088a000000000000 // also accept actually supported DISPLAY_P3 intent
    orr x8, x8, x20
    str x8, [sp, #32]
    mov x0, x19
    add x1, sp, #32
    bl op13_original_find_mode
    cbz x0, 7f
    ldr w8, [x0, #0x20]
    cmp w8, w20
    b.ne 7f
6:
    mov w0, #1
    b 8f
7:
    mov w0, #0
8:
    ldp x19, x20, [sp, #16]
    ldp x29, x30, [sp], #48
    .inst 0xd50323bf // autiasp
    ret
.size op13_has_render_intent, .-op13_has_render_intent
