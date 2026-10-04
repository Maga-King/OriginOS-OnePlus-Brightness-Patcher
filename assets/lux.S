// Entered with x19=sensors_event_t*, x20=VivoFusionImpl*, w0=isUnderLight.
// The HAL publishes 0x3e9 with valid lux in data[0] and a parallel 0x6a5
// private alias with the same timestamp. Feed the policy filter only once.
// Other sensor handles retain the original UnderLight/ProjectFeature path.
.text
.p2align 2
.global mio_oplus_policy_lux
mio_oplus_policy_lux:
    ldr w8, [x19, #4]
    cmp w8, #0x3e9
    b.eq .Lstandard
    cmp w8, #0x6a5
    b.ne .Loriginal
    ldr w9, [x19, #8]
    mov w8, #0x3f7
    movk w8, #1, lsl #16
    cmp w9, w8
    b.eq mio_after_policy
    b .Loriginal
.Lstandard:
    ldr w9, [x19, #8]
    cmp w9, #5
    b.eq mio_policy_process
    mov w8, #0x3f7
    movk w8, #1, lsl #16
    cmp w9, w8
    b.eq mio_policy_process
.Loriginal:
    tbz w0, #0, .Lproject
    b mio_under_light
.Lproject:
    b mio_project_light
