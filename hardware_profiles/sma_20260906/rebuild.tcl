# Vivado 2018.3 batch rebuild into a NEW directory; source project is untouched.
# Usage: vivado -mode batch -source rebuild.tcl -tclargs <source-project-dir> <new-build-dir>
if {$argc != 2} {error "Expected source project directory and a NEW build directory"}
set source_project [file normalize [lindex $argv 0]]
set project [file normalize [lindex $argv 1]]
if {[file exists $project]} {error "Refusing to overwrite existing build directory: $project"}
foreach part {AD9361_test2.xpr AD9361_test2.srcs ip_repo} {
    if {![file exists [file join $source_project $part]]} {error "Missing source: $part"}
}
file mkdir $project
foreach part {AD9361_test2.xpr AD9361_test2.srcs ip_repo} {
    file copy [file join $source_project $part] [file join $project $part]
}
file mkdir [file join $project AD9361_test2.ip_user_files]
file mkdir [file join $project AD9361_test2.cache ip]
# Rebase three packaged ROM initialization paths INSIDE the new build copy.
# The old checkout embeds an obsolete absolute AD9361_test2_ofdm path.
foreach name {deinter_lut atan_lut rot_lut} {
    set xci [file join $project ip_repo openofdm_rx src $name ${name}.xci]
    set coe [file join $project ip_repo openofdm_rx src ${name}.coe]
    if {![file isfile $coe]} {error "Missing ROM initialization: $coe"}
    set fh [open $xci r]
    fconfigure $fh -encoding utf-8 -translation binary
    set content [read $fh]
    close $fh
    set count [regexp -indices {<spirit:configurableElementValue spirit:referenceId="PARAM_VALUE.Coe_File">([^<]*)</spirit:configurableElementValue>} $content match value_range]
    if {$count != 1} {error "Unexpected ROM XCI layout: $xci"}
    lassign $value_range value_start value_end
    set coe_xml [string map {& &amp; < &lt; > &gt;} $coe]
    set content [string replace $content $value_start $value_end $coe_xml]
    set fh [open $xci w]
    fconfigure $fh -encoding utf-8 -translation binary
    puts -nonewline $fh $content
    close $fh
}
set reports [file join $project build_reports]
file mkdir $reports
open_project [file join $project AD9361_test2.xpr]
set_property IP.USER_FILES_DIR [file join $project AD9361_test2.ip_user_files] [current_project]
set_property IP_OUTPUT_REPO [file join $project AD9361_test2.cache ip] [current_project]
# Create the isolated output directories before open_project (launcher).
# Vivado 2018.3 otherwise silently falls back to the original project's
# ip_user_files directory. Property names are version-specific.
foreach prop [list_property [current_project]] {
    if {[string match -nocase *ip*dir* $prop] || [string match -nocase *ip*repo* $prop]} {
        puts "ISOLATION_PROPERTY $prop [get_property $prop [current_project]]"
    }
}
set_property IP_REPO_PATHS [list [file join $project ip_repo]] [current_project]
foreach old [get_files -quiet *AD9361_test2_ofdm*] { remove_files $old }
update_ip_catalog -rebuild
set bd_file [file join $project AD9361_test2.srcs sources_1 bd System System.bd]
open_bd_design $bd_file
set ps [get_bd_cells processing_system7_0]
set_property -dict [list CONFIG.PCW_EN_CLK3_PORT {1} CONFIG.PCW_FPGA_FCLK3_ENABLE {1} CONFIG.PCW_FPGA3_PERIPHERAL_FREQMHZ {41.666667} CONFIG.PCW_FCLK_CLK3_BUF {FALSE}] $ps
if {[get_property CONFIG.PCW_FPGA2_PERIPHERAL_FREQMHZ $ps] != 40} { error "RX transport clock must stay 40 MHz" }
if {![llength [get_bd_cells -quiet rst_tx_transport]]} {
    create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_tx_transport
}
if {![llength [get_bd_nets -of_objects [get_bd_pins rst_tx_transport/slowest_sync_clk]]]} {
    connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK3] [get_bd_pins rst_tx_transport/slowest_sync_clk]
}
if {![llength [get_bd_nets -of_objects [get_bd_pins rst_tx_transport/ext_reset_in]]]} {
    connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] [get_bd_pins rst_tx_transport/ext_reset_in]
}
foreach name {tx_intf_0/dac_clk axis_data_fifo_3/s_axis_aclk} {
    set pin [get_bd_pins $name]
    foreach old [get_bd_nets -of_objects $pin] { disconnect_bd_net $old $pin }
    connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK3] $pin
}
foreach {name reset} {tx_intf_0/dac_rst peripheral_reset axis_data_fifo_3/s_axis_aresetn peripheral_aresetn} {
    set pin [get_bd_pins $name]
    foreach old [get_bd_nets -of_objects $pin] { disconnect_bd_net $old $pin }
    connect_bd_net [get_bd_pins rst_tx_transport/$reset] $pin
}
validate_bd_design
if {[get_property CONFIG.C_EXT_RESET_HIGH [get_bd_cells rst_tx_transport]] != 0} {error "TX reset polarity mismatch"}
puts "TX_CLOCK_HZ [get_property CONFIG.FREQ_HZ [get_bd_pins processing_system7_0/FCLK_CLK3]]"
save_bd_design
set bd [get_files $bd_file]
reset_target all $bd
generate_target all $bd
export_ip_user_files -of_objects $bd -no_script -sync -force -quiet
update_compile_order -fileset sources_1
report_ip_status -file [file join $reports ip_status.rpt]
foreach run [get_runs -quiet *_synth_1] { reset_run $run }
reset_run synth_1
launch_runs synth_1 -jobs 6
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne {100%}} {error "Synthesis failed"}
reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 6
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne {100%}} {error "Implementation failed"}
open_run impl_1
report_timing_summary -delay_type min_max -report_unconstrained -max_paths 30 -file [file join $reports timing.rpt]
report_cdc -details -file [file join $reports cdc.rpt]
report_drc -file [file join $reports drc.rpt]
set impl [get_property DIRECTORY [get_runs impl_1]]
write_hwdef -force -file [file join $reports System_wrapper.hwdef]
write_sysdef -hwdef [file join $reports System_wrapper.hwdef] -bitfile [file join $impl System_wrapper.bit] -file [file join $reports System_wrapper.hdf]
write_debug_probes -force [file join $reports System_wrapper.ltx]
file copy -force [file join $project AD9361_test2.srcs sources_1 bd System ip System_processing_system7_0_0 ps7_init.tcl] [file join $reports ps7_init.tcl]
file copy -force [file join $impl System_wrapper.bit] [file join $reports System_wrapper.bit]
puts "ISOLATED_BUILD_DONE $project"
puts "Timing violations do NOT mean a production-ready image; inspect timing.rpt/cdc.rpt and run the link tests."
close_project
