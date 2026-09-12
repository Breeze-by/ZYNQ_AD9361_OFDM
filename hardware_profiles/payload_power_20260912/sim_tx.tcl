set here [file dirname [file normalize [info script]]]
set src E:/by2025/AD9361_test_board/ad9361_stage17_power_c_20260912/ip_repo/openofdm_tx/src
set out E:/by2025/AD9361_test_board/stage17-tx-sim-c
if {[file exists [file join $out stage17_tx.xpr]]} {
    open_project [file join $out stage17_tx.xpr]
} else {
create_project stage17_tx $out -part xc7z020clg484-1
set_property target_simulator XSim [current_project]
set_property XPM_LIBRARIES {XPM_CDC XPM_MEMORY XPM_FIFO} [current_project]
add_files [glob [file join $src *.v]]
set_property include_dirs $src [get_filesets sources_1]
foreach mem [glob [file join $src *.mem]] {
    add_files -fileset sim_1 $mem
    set_property file_type {Memory Initialization Files} [get_files $mem]
}
add_files -fileset sim_1 [file join $here tx_tb.v]
}
set_property file_type SystemVerilog [get_files tx_tb.v]
set_property top tx_tb [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
update_compile_order -fileset sim_1
launch_simulation
run all
close_sim
close_project
puts STAGE17_TX_PROJECT_COMPLETE
