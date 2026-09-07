# Vivado 2018.3: merge the accepted TX transport clock into an ORIGINAL project.
# Close other Vivado windows using this project first.
# Usage: vivado -mode batch -source merge_into_project.tcl -tclargs <project-dir> <new-report-dir>
# Saves source backups; validates and generates BD output products only.
# Does NOT synthesize/implement, export SDK hardware, program a board, or touch ELF/BSP.
if {$argc != 2} {error "Expected project directory and a NEW report/backup directory"}
if {![string match "2018.3*" [version -short]]} {error "Use Vivado 2018.3"}
set project [file normalize [lindex $argv 0]]
set reports [file normalize [lindex $argv 1]]
if {[file exists $reports]} {error "Refusing to overwrite existing reports: $reports"}
set bd_rel AD9361_test2.srcs/sources_1/bd/System/System.bd
set inputs [list AD9361_test2.xpr $bd_rel]
foreach name {deinter_lut atan_lut rot_lut} {
    lappend inputs ip_repo/openofdm_rx/src/$name/${name}.xci
    if {![file isfile [file join $project ip_repo openofdm_rx src ${name}.coe]]} {
        error "Missing ROM contents: $name"
    }
}
foreach relative $inputs {
    if {![file isfile [file join $project $relative]]} {error "Missing input: $relative"}
}
file mkdir $reports
foreach relative $inputs {
    set destination [file join $reports backup $relative]
    file mkdir [file dirname $destination]
    file copy [file join $project $relative] $destination
}

# Same source-location repair as rebuild.tcl. ROM contents are never changed.
# Relative to the XCI directory; works when the original project is moved/copied.
foreach name {deinter_lut atan_lut rot_lut} {
    set xci [file join $project ip_repo openofdm_rx src $name ${name}.xci]
    set fh [open $xci r]
    fconfigure $fh -encoding utf-8 -translation binary
    set content [read $fh]
    close $fh
    if {[regexp -indices {<spirit:configurableElementValue spirit:referenceId="PARAM_VALUE.Coe_File">([^<]*)</spirit:configurableElementValue>} $content match value_range] != 1} {
        error "Unexpected ROM XCI layout: $xci"
    }
    lassign $value_range first last
    set updated [string replace $content $first $last ../${name}.coe]
    if {$updated ne $content} {
        set fh [open $xci w]
        fconfigure $fh -encoding utf-8 -translation binary
        puts -nonewline $fh $updated
        close $fh
    }
}

open_project [file join $project AD9361_test2.xpr]
set_property IP_REPO_PATHS [list [file join $project ip_repo]] [current_project]
# Remove only stale duplicate ROM references, never files on disk.
foreach name {deinter_lut atan_lut rot_lut} {
    foreach old [get_files -quiet *AD9361_test2_ofdm*/${name}.coe] {remove_files $old}
}
update_ip_catalog -rebuild
set bd_file [file join $project $bd_rel]
open_bd_design $bd_file
set ps [get_bd_cells processing_system7_0]
foreach {property expected} {
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ 100
    CONFIG.PCW_FPGA1_PERIPHERAL_FREQMHZ 200
    CONFIG.PCW_FPGA2_PERIPHERAL_FREQMHZ 40
} {
    if {[get_property $property $ps] != $expected} {error "Unexpected baseline $property"}
}
proc source_for {pin_name} {
    set net [get_bd_nets -quiet -of_objects [get_bd_pins $pin_name]]
    if {[llength $net] != 1} {error "Expected one net at $pin_name"}
    return [get_bd_pins -quiet -of_objects $net -filter {DIR == O}]
}
proc require_source {pin_name allowed} {
    set drivers [source_for $pin_name]
    if {[llength $drivers] != 1} {error "Expected one driver at $pin_name: $drivers"}
    set actual [string trimleft [lindex $drivers 0] /]
    if {[lsearch -exact $allowed $actual] < 0} {error "Unexpected source at $pin_name: $actual"}
}
foreach pin {tx_intf_0/dac_clk axis_data_fifo_3/s_axis_aclk} {
    require_source $pin {processing_system7_0/FCLK_CLK2 processing_system7_0/FCLK_CLK3}
}
require_source tx_intf_0/dac_rst {rst_ps7_0_40M/peripheral_reset rst_tx_transport/peripheral_reset}
require_source axis_data_fifo_3/s_axis_aresetn {rst_ps7_0_40M/peripheral_aresetn rst_tx_transport/peripheral_aresetn}
set_property -dict [list \
    CONFIG.PCW_EN_CLK3_PORT {1} \
    CONFIG.PCW_FPGA_FCLK3_ENABLE {1} \
    CONFIG.PCW_FPGA3_PERIPHERAL_FREQMHZ {41.666667} \
    CONFIG.PCW_FCLK_CLK3_BUF {FALSE}] $ps
if {![llength [get_bd_cells -quiet rst_tx_transport]]} {
    create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_tx_transport
}
proc connect_source {source destination} {
    set pin [get_bd_pins $destination]
    foreach net [get_bd_nets -quiet -of_objects $pin] {disconnect_bd_net $net $pin}
    connect_bd_net [get_bd_pins $source] $pin
}
foreach pin {rst_tx_transport/slowest_sync_clk tx_intf_0/dac_clk axis_data_fifo_3/s_axis_aclk} {
    connect_source processing_system7_0/FCLK_CLK3 $pin
}
connect_source processing_system7_0/FCLK_RESET0_N rst_tx_transport/ext_reset_in
connect_source rst_tx_transport/peripheral_reset tx_intf_0/dac_rst
connect_source rst_tx_transport/peripheral_aresetn axis_data_fifo_3/s_axis_aresetn
validate_bd_design
if {[get_property CONFIG.C_EXT_RESET_HIGH [get_bd_cells rst_tx_transport]] != 0} {
    error "TX reset polarity mismatch"
}
foreach pin {rst_tx_transport/slowest_sync_clk tx_intf_0/dac_clk axis_data_fifo_3/s_axis_aclk} {
    require_source $pin {processing_system7_0/FCLK_CLK3}
}
foreach pin {rst_ps7_0_40M/slowest_sync_clk axis_data_fifo_4/m_axis_aclk rx_intf_0/adc_clk c_shift_ram_0/CLK adc_valid_hold_adapt_0/clk} {
    require_source $pin {processing_system7_0/FCLK_CLK2}
}
require_source tx_intf_0/dac_rst {rst_tx_transport/peripheral_reset}
require_source axis_data_fifo_3/s_axis_aresetn {rst_tx_transport/peripheral_aresetn}
require_source rx_intf_0/adc_rst {rst_ps7_0_40M/peripheral_reset}
require_source rst_tx_transport/ext_reset_in {processing_system7_0/FCLK_RESET0_N}
set tx_hz [get_property CONFIG.FREQ_HZ [get_bd_pins processing_system7_0/FCLK_CLK3]]
if {abs($tx_hz - 41666667.0) > 5} {error "Unexpected TX frequency: $tx_hz"}
save_bd_design
set bd [get_files $bd_file]
# Original output products contain copies of the obsolete ROM paths.
# Recreate them from the repaired source IP package rather than reusing them.
reset_target all $bd
generate_target all $bd
export_ip_user_files -of_objects $bd -no_script -sync -force -quiet
update_compile_order -fileset sources_1
report_ip_status -file [file join $reports ip_status.rpt]
write_bd_tcl -force [file join $reports merged_system.tcl]
puts "ORIGINAL_PROJECT_MERGE_OK TX_HZ=$tx_hz RX_HZ=40000000 RESET_POLARITY=ACTIVE_LOW"
puts "BD output products generated. Existing bit/HDF/ELF have NOT been replaced or downloaded."
puts "Next: Generate Bitstream, Export Hardware (Include bitstream), update SDK hardware/BSP, build ELF."
close_project
