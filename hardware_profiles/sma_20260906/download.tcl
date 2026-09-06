# Run from the Xilinx SDK 2018.3 XSCT Console. This resets/programs the local
# JTAG board only; it does not write flash/SD or change the other board.
# The matching ps7_init.tcl is required: AD9361 Fs stays 40 MSPS; FCLK3 feeds
# the TX transport at 41.667 MHz, while FCLK2 keeps RX transport at 40 MHz.
set profile_dir [file normalize [file dirname [info script]]]
set sdk_dir [file normalize [file join $profile_dir .. ..]]
set bit_file [file join $profile_dir System_wrapper.bit]
set init_file [file join $profile_dir ps7_init.tcl]
set elf_file [file join $sdk_dir AD9361_test2 Debug AD9361_test2.elf]
foreach path [list $bit_file $init_file $elf_file] {
    if {![file isfile $path]} {error "Missing download input: $path"}
}
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
rst -system
after 2000
targets -set -filter {name =~ "xc7z020"}
fpga -file $bit_file
targets -set -filter {name =~ "ARM*#0"}
source $init_file
ps7_init
foreach {address expected} {
    0xf8000170 0x00200500
    0xf8000180 0x00100500
    0xf8000190 0x00500500
    0xf80001a0 0x00400600
} {
    if {[expr [mrd -value $address]] != $expected} {
        disconnect
        error "Unexpected clock divider at $address; CPU left stopped"
    }
}
ps7_post_config
dow $elf_file
con
puts "SMA profile loaded: TX transport FCLK3=41.667 MHz, RX FCLK2=40 MHz; AD9361=40 MSPS"
puts "Experimental bench profile; residual packet loss / timing limitations are documented in README.md"
disconnect
