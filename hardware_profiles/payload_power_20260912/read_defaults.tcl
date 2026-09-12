# Non-mutating final verification. Resolve DDR addresses from the current ELF.
if {$argc != 1 || [lindex $argv 0] ni {sender receiver}} {error "Expected role"}
set role [lindex $argv 0]
set repo E:/by2025/AD9361_test_board/AD9361_test2/AD9361_test2.sdk
if {$role eq "sender"} {set sdk D:/vivado2018/SDK/2018.3;set gain 36;set att 16000} else {set sdk D:/Xilinx/SDK/2018.3;set gain 66;set att 25000}
set table [exec [file join $sdk gnu aarch32 nt gcc-arm-none-eabi bin arm-none-eabi-nm.exe] -n [file join $repo AD9361_test2 Debug AD9361_test2.elf]]
proc symbol {name} {
    global table
    if {![regexp -line [format {^([0-9a-f]+) [A-Za-z] %s$} $name] $table unused hex]} {error "Missing symbol $name"}
    return [scan $hex %x]
}
proc u32 {a} {return [expr {[mrd -value $a] & 0xffffffff}]}
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
loadhw -hw [file join $repo System_wrapper_hw_platform_0 system.hdf] -mem-ranges [list {0x40000000 0x4000ffff}]
foreach {a expected} {
    0xf8000170 0x00200500 0xf8000180 0x00100500 0xf8000190 0x00500500 0xf80001a0 0x00400600
    0x40000050 0xA7170002 0x4000207c 0xA7170002
    0x40000008 0xA704205D 0x40002014 0xA7048304
    0x40002004 0x101 0x40002008 0x00300000 0x4000200c 63
} {if {[u32 $a] != $expected} {error "Configuration changed at $a"}}
if {[u32 [symbol gain]] != $gain || [u32 [symbol txatt]] != $att || [u32 [symbol sample_rate]] != 40000000} {error "Role RF configuration changed"}
if {$role eq "receiver"} {
    set a [symbol loopback_return_port]
    set port [expr {([u32 [expr {$a & ~3}]] >> (($a & 3)*8)) & 0xffff}]
    if {$port != 15002} {error "GUI port not restored: $port"}
    set ip [u32 [symbol loopback_return_addr]]
    if {$ip != 0x6401A8C0} {error [format "GUI IP not restored: %08X" $ip]}
    puts "STAGE18_GUI_PEER_VERIFIED 192.168.1.100:15002"
}
puts "STAGE18_FINAL_RUNTIME_VERIFIED role=$role gain=$gain txatt=$att guard=32 shift=4 plateau=63"
disconnect
