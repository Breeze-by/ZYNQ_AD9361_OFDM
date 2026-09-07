# Vivado 2018.3: merge ONLY the validated long-sync history fix into an original project.
# Close all other Vivado windows for the target project first.
# Args: <project-dir> <NEW backup/report-dir> <git-executable>
# Regenerates BD/IP outputs and checks syntax. Does not generate/download a bit,
# export SDK hardware, change clocks/RF settings, or modify C/ELF/BSP files.
if {$argc != 3} {error "Expected project, NEW report directory, and git executable"}
if {![string match "2018.3*" [version -short]]} {error "Use Vivado 2018.3"}
set project [file normalize [lindex $argv 0]]
set reports [file normalize [lindex $argv 1]]
set git [file normalize [lindex $argv 2]]
set patch [file join [file dirname [file normalize [info script]]] sync_long.patch]
set rtl_rel ip_repo/openofdm_rx/src/sync_long.v
set component_rel ip_repo/openofdm_rx/component.xml
set bd_rel AD9361_test2.srcs/sources_1/bd/System/System.bd
if {[file exists $reports]} {error "Refusing to overwrite reports: $reports"}
foreach f [list $git $patch [file join $project AD9361_test2.xpr] [file join $project $bd_rel] \
        [file join $project $rtl_rel] [file join $project $component_rel]] {
    if {![file isfile $f]} {error "Missing input: $f"}
}
proc read_text {path} {
    set f [open $path r]
    fconfigure $f -encoding utf-8
    set result [read $f]
    close $f
    return $result
}
proc write_text {path value} {
    set f [open $path w]
    fconfigure $f -encoding utf-8 -translation lf
    puts -nonewline $f $value
    close $f
}
set component [file join $project $component_rel]
set xml [read_text $component]
if {![regexp {<xilinx:coreRevision>([23])</xilinx:coreRevision>} $xml unused revision]} {
    error "Expected original RX IP revision 2 or merged revision 3; never use an instrumented IP"
}
if {[string first stage5_diag $xml] >= 0} {error "Diagnostic IP must not be merged"}
set previous_dir [pwd]
cd $project
file mkdir $reports
# Git checkout can convert a .patch to CRLF while the vendor RTL remains LF.
# Normalize the patch copy only, never rewrite unrelated source whitespace.
set normalized_patch [file join $reports sync_long.lf.patch]
write_text $normalized_patch [read_text $patch]
if {$revision == 2} {
    exec $git apply --check --whitespace=nowarn $normalized_patch
} else {
    exec $git apply --reverse --check --whitespace=nowarn $normalized_patch
    puts "SYNC_LATE_SOURCE_ALREADY_MERGED; refreshing and verifying generated outputs"
}
set inputs [list AD9361_test2.xpr $bd_rel $rtl_rel $component_rel]
set generated_xcis [glob -nocomplain -directory [file join $project AD9361_test2.srcs sources_1 bd System ip] System_openofdm_rx*/*.xci]
foreach f $generated_xcis {lappend inputs [string range $f [expr {[string length $project]+1}] end]}
foreach rel $inputs {
    set source [file join $project $rel]
    if {![file isfile $source]} {error "Missing backup input: $rel"}
    set destination [file join $reports backup $rel]
    file mkdir [file dirname $destination]
    file copy $source $destination
}
if {$revision == 2} {
    exec $git apply --whitespace=nowarn $normalized_patch
    exec $git apply --reverse --check --whitespace=nowarn $normalized_patch
    write_text $component [string map {<xilinx:coreRevision>2</xilinx:coreRevision> <xilinx:coreRevision>3</xilinx:coreRevision>} $xml]
}
cd $previous_dir
set expected [string trimright [read_text [file join $project $rtl_rel]] "\n"]

open_project [file join $project AD9361_test2.xpr]
set_property IP_REPO_PATHS [list [file join $project ip_repo]] [current_project]
update_ip_catalog -rebuild
set bd_file [file join $project $bd_rel]
open_bd_design $bd_file
set rx_ip [get_ips -quiet *openofdm_rx*]
if {[llength $rx_ip] != 1} {error "Expected one original RX IP"}
upgrade_ip $rx_ip
if {[llength [get_bd_pins -quiet openofdm_rx_0/stage5_diag_gray]]} {error "Unexpected diagnostic port"}
proc require_driver {destination source} {
    set net [get_bd_nets -quiet -of_objects [get_bd_pins $destination]]
    set drivers [get_bd_pins -quiet -of_objects $net -filter {DIR == O}]
    if {[llength $drivers] != 1 || [string trimleft [lindex $drivers 0] /] ne $source} {
        error "Changed clock/reset at $destination: $drivers"
    }
}
foreach pin {tx_intf_0/dac_clk axis_data_fifo_3/s_axis_aclk rst_tx_transport/slowest_sync_clk} {
    require_driver $pin processing_system7_0/FCLK_CLK3
}
foreach pin {rx_intf_0/adc_clk axis_data_fifo_4/m_axis_aclk rst_ps7_0_40M/slowest_sync_clk} {
    require_driver $pin processing_system7_0/FCLK_CLK2
}
require_driver tx_intf_0/dac_rst rst_tx_transport/peripheral_reset
require_driver rx_intf_0/adc_rst rst_ps7_0_40M/peripheral_reset
set ps [get_bd_cells processing_system7_0]
foreach {index frequency} {0 100 1 200 2 40 3 41.666667} {
    if {abs([get_property CONFIG.PCW_FPGA${index}_PERIPHERAL_FREQMHZ $ps] - $frequency) > 0.001} {
        error "Unexpected FCLK$index frequency"
    }
}
validate_bd_design
save_bd_design
set bd [get_files $bd_file]
reset_target all $bd
generate_target all $bd
export_ip_user_files -of_objects $bd -no_script -sync -force -quiet
update_compile_order -fileset sources_1
report_ip_status -file [file join $reports ip_status.rpt]
write_bd_tcl -force [file join $reports merged_system.tcl]
set copies [get_files -all -quiet *sync_long.v]
if {![llength $copies]} {error "No generated sync_long source found"}
set generated_count 0
foreach copy $copies {
    set path [file normalize [get_property NAME $copy]]
    if {[string trimright [read_text $path] "\n"] ne $expected} {
        error "Generated RX source differs from merged source: $path"
    }
    puts "SYNC_LATE_SOURCE_VERIFIED $path"
    if {[string first /ipshared/ [string map {\\ /} $path]] >= 0} {incr generated_count}
}
if {$generated_count == 0} {error "Did not verify a regenerated IP shared source"}
check_syntax -fileset sources_1
foreach run {synth_1 impl_1} {
    puts "SYNC_LATE_RUN $run STATUS=[get_property STATUS [get_runs $run]] NEEDS_REFRESH=[get_property NEEDS_REFRESH [get_runs $run]]"
}
puts "SYNC_LATE_ORIGINAL_MERGE_OK RX_IP_REVISION=3 TX_HZ=41666667 RX_HZ=40000000"
puts "Existing bit/HDF/ELF and running boards have NOT been replaced. Generate Bitstream and export matching hardware before download."
close_project
