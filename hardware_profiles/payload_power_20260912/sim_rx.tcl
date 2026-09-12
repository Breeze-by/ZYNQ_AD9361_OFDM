# Full, noiseless TX-to-RX simulation with a private copy of the RX vendor IP.
set here [file dirname [file normalize [info script]]]
set out E:/by2025/AD9361_test_board/stage17-rx-sim
set original E:/by2025/AD9361_test_board/ad9361_stage17_power_c_20260912/ip_repo/openofdm_rx/src
set waves E:/by2025/AD9361_test_board/stage17-tx-sim-c/stage17_tx.sim/sim_1/behav/xsim
if {[file exists [file join $out project stage17_rx.xpr]]} {
    open_project [file join $out project stage17_rx.xpr]
} else {
file mkdir $out
file copy $original [file join $out src]
set src [file join $out src]
foreach name {deinter_lut atan_lut rot_lut} {
    set xci [file join $src $name ${name}.xci]
    set f [open $xci r]; set t [read $f]; close $f
    set coe [file join $src ${name}.coe]
    if {[regsub {(<spirit:configurableElementValue spirit:referenceId="PARAM_VALUE.Coe_File">)[^<]*(</spirit:configurableElementValue>)} $t "\\1$coe\\2" t] != 1} {error "ROM layout: $name"}
    set f [open $xci w]; puts -nonewline $f $t; close $f
}
create_project stage17_rx [file join $out project] -part xc7z020clg484-1
set_property target_simulator XSim [current_project]
set_property XPM_LIBRARIES {XPM_CDC XPM_MEMORY XPM_FIFO} [current_project]
set files {}
foreach v [glob [file join $src *.v]] {
    if {[file tail $v] ni {dot11_tb.v common_params.v common_defs.v openofdm_rx_pre_def.v openofdm_rx_git_rev.v}} {lappend files $v}
}
add_files $files
set_property include_dirs $src [get_filesets sources_1]
foreach xci [glob [file join $src * *.xci]] {read_ip $xci}
generate_target simulation [get_ips]
add_files -fileset sim_1 [file join $here rx_tb.v]
set_property file_type SystemVerilog [get_files rx_tb.v]
foreach mem [concat [glob [file join $waves wave*.mem]] [list [file join $waves payload.hex]]] {
    add_files -fileset sim_1 $mem
    set_property file_type {Memory Initialization Files} [get_files $mem]
}
set_property top rx_tb [get_filesets sim_1]
}
# Replace only this isolated simulation's generated waveform inputs on rerun.
foreach old [get_files -quiet -of_objects [get_filesets sim_1] *wave*.mem] {remove_files $old}
foreach old [get_files -quiet -of_objects [get_filesets sim_1] *payload.hex] {remove_files $old}
foreach mem [concat [glob [file join $waves wave*.mem]] [list [file join $waves payload.hex]]] {
    add_files -fileset sim_1 $mem
    set_property file_type {Memory Initialization Files} [get_files $mem]
}
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sim_1
launch_simulation
run all
close_sim
close_project
puts STAGE17_RX_PROJECT_COMPLETE
