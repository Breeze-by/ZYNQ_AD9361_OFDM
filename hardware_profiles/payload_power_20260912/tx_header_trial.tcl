# Bounded antenna comparison: change only TX RF attenuation in RAM.
# 22 dB + DATA 1/8 versus 16 dB + DATA 1/16 approximately holds DATA power
# constant while raising the protected region by 6 dB. No source/ELF/Flash write.
if {$argc != 1 || [lindex $argv 0] ni {16 22}} {error "Expected attenuation 16 or 22 dB"}
if {[string tolower $env(USERNAME)] ne "hardware_simulation"} {error "Sender PC only"}
set atten_db [lindex $argv 0]
set diag [file normalize [file join $env(TEMP) ad9361-diag-20260906]]
set elf [file join $diag stage17-before-power AD9361_test2.elf]
set hdf [file join $diag stage17-image system.hdf]
set nm D:/vivado2018/SDK/2018.3/gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-nm.exe
foreach f [list $elf $hdf $nm] {if {![file isfile $f]} {error "Missing input $f"}}
set table [exec $nm -n $elf]
proc symbol {name} {
    global table
    if {![regexp -line [format {^([0-9a-f]+) [A-Za-z] %s$} $name] $table unused hex]} {error "Missing symbol $name"}
    return [scan $hex %x]
}
set att_addr [symbol txatt]
set gain_addr [symbol gain]
proc u32 {a} {return [expr {[mrd -value $a] & 0xffffffff}]}
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
loadhw -hw $hdf -mem-ranges [list {0x40000000 0x4000ffff}]
foreach a {0x40000050 0x4000207c} {if {[u32 $a] != 0xa7170002} {error "Not D candidate; no writes"}}
if {[u32 $att_addr] ni {16000 22000} || [u32 $gain_addr] != 36} {error "Unexpected TX baseline; no writes"}
targets -set -filter {name =~ "ARM*#0"}
stop
rst -processor
dow $elf
if {[u32 $att_addr] != 22000 || [u32 $gain_addr] != 36} {error "Wrong role ELF; CPU remains stopped"}
mwr $att_addr [expr {$atten_db*1000}]
con
after 12000
targets -set -filter {name =~ "APU"}
foreach {address expected} {0xf8000170 0x00200500 0xf8000180 0x00100500 0xf8000190 0x00500500 0xf80001a0 0x00400600 0x40002004 0x101 0x40002008 0x00300000 0x4000200c 63 0x40000050 0xa7170002 0x4000207c 0xa7170002} {
    if {[u32 $address] != $expected} {error "Unexpected readback $address"}
}
if {[u32 $att_addr] != $atten_db*1000 || [u32 $gain_addr] != 36} {error "RF parameter readback mismatch"}
puts "STAGE17_HEADER_TRIAL_READY TX_ATT_DB=$atten_db RX_GAIN=36; reapply both DATA power levels before testing"
disconnect
