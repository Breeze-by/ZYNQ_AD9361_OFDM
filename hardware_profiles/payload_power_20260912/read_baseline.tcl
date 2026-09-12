# Read-only board identification; loadhw supplies the debugger memory map.
set project E:/by2025/AD9361_test_board/AD9361_test2
set platform [file join $project AD9361_test2.sdk System_wrapper_hw_platform_0]
connect -url tcp:127.0.0.1:3121
# A newly launched hw_server may return before USB/JTAG discovery completes.
for {set attempt 0} {$attempt < 10} {incr attempt} {
    if {[llength [targets -target-properties -filter {name =~ "APU"}]] > 0} {break}
    after 1000
}
targets -set -filter {name =~ "APU"}
loadhw -hw [file join $platform system.hdf] -mem-ranges [list {0x40000000 0x4000ffff}]
proc u32 {a} {return [expr {[mrd -value $a] & 0xffffffff}]}
foreach {name address} {
    FCLK0_PL 0xf8000170 FCLK1_BUS 0xf8000180
    FCLK2_RX 0xf8000190 FCLK3_TX 0xf80001a0
    RX_ENABLE 0x40002004 RX_POWER 0x40002008 RX_PLATEAU 0x4000200c
    RX_REG4 0x40002010 RX_REG5 0x40002014 TX_REG2 0x40000008
    RX_GAIN 0x001528cc TX_ATT_MDB 0x001528d0 SAMPLE_RATE 0x001528b0
    GUI_IP 0x002186e8 GUI_PORT 0x002186ec
} {puts [list STAGE17_BASELINE $name [u32 $address]]}
puts STAGE17_BASELINE_READ_COMPLETE
disconnect
