# Authorized original-project merge. Args: project, verified backup, NEW reports.
# No board access. Reuses the SAME reviewed patch as the isolated candidate.
if {$argc != 3} {error "Expected project backup reports"}
if {![string match "2018.3*" [version -short]]} {error "Use Vivado 2018.3"}
lassign $argv project backup reports
foreach name {project backup reports} {set $name [file normalize [set $name]]}
if {[file exists $reports]} {error "Preserve existing build reports"}
set profile [file dirname [file normalize [info script]]]
proc read_text {p} {set f [open $p r]; fconfigure $f -encoding utf-8; set s [read $f]; close $f; return $s}
proc write_text {p s} {set f [open $p w]; fconfigure $f -encoding utf-8 -translation lf; puts -nonewline $f $s; close $f}
set modified {sync_long.v dot11.v openofdm_rx.v openofdm_rx_s_axi.v}
set inputs {AD9361_test2.xpr AD9361_test2.srcs/sources_1/bd/System/System.bd ip_repo/openofdm_rx/component.xml}
foreach name $modified {lappend inputs ip_repo/openofdm_rx/src/$name}
foreach rel $inputs {
    if {[read_text [file join $project $rel]] ne [read_text [file join $backup $rel]]} {error "Changed after backup: $rel"}
}
if {[file exists [file join $project ip_repo openofdm_rx src payload_snr_monitor.v]]} {error "Already merged; do not double patch"}
file mkdir $reports
set staged [file join $reports staging]
file mkdir [file join $staged ip_repo openofdm_rx src]
foreach rel [lrange $inputs 2 end] {file copy [file join $project $rel] [file join $staged $rel]}
set candidate_code [read_text [file join $profile build.tcl]]
set boundary [string first {set template [read_text} $candidate_code]
if {$boundary < 0} {error "Candidate patch boundary missing"}
# This prefix only declares helper procedures; it does not open/build a project.
set argc 2
set argv [list $project $staged]
eval [string range $candidate_code 0 [expr {$boundary-1}]]
patch_candidate $staged
foreach name [concat $modified {payload_snr_monitor.v}] {
    file copy -force [file join $staged ip_repo openofdm_rx src $name] [file join $project ip_repo openofdm_rx src $name]
}
file copy -force [file join $staged ip_repo openofdm_rx component.xml] [file join $project ip_repo openofdm_rx component.xml]
puts SNR_ORIGINAL_RTL_MERGED
open_project [file join $project AD9361_test2.xpr]
set_property IP_REPO_PATHS [list [file join $project ip_repo]] [current_project]
update_ip_catalog -rebuild
set bd_file [file join $project AD9361_test2.srcs sources_1 bd System System.bd]
open_bd_design $bd_file
set rx_ip [get_ips -quiet *openofdm_rx*]
if {[llength $rx_ip] != 1} {error "Expected one RX IP"}
upgrade_ip $rx_ip
proc require_driver {destination source} {
    set net [get_bd_nets -quiet -of_objects [get_bd_pins $destination]]
    set drivers [get_bd_pins -quiet -of_objects $net -filter {DIR == O}]
    if {[llength $drivers]!=1 || [string trimleft [lindex $drivers 0] /] ne $source} {error "Unexpected clock/reset driver at $destination"}
}
foreach pin {tx_intf_0/dac_clk axis_data_fifo_3/s_axis_aclk rst_tx_transport/slowest_sync_clk} {require_driver $pin processing_system7_0/FCLK_CLK3}
foreach pin {rx_intf_0/adc_clk axis_data_fifo_4/m_axis_aclk rst_ps7_0_40M/slowest_sync_clk} {require_driver $pin processing_system7_0/FCLK_CLK2}
require_driver openofdm_rx_0/s00_axi_aclk processing_system7_0/FCLK_CLK0
foreach {index mhz} {0 100 1 200 2 40 3 41.666667} {
    if {abs([get_property CONFIG.PCW_FPGA${index}_PERIPHERAL_FREQMHZ [get_bd_cells processing_system7_0]]-$mhz)>0.001} {error "Unexpected FCLK$index"}
}
validate_bd_design
save_bd_design
set bd [get_files $bd_file]
reset_target all $bd
generate_target all $bd
export_ip_user_files -of_objects $bd -no_script -sync -force -quiet
update_compile_order -fileset sources_1
foreach name [concat $modified {payload_snr_monitor.v}] {
    set expected [string trimright [read_text [file join $project ip_repo openofdm_rx src $name]] "\n"]
    set verified 0
    foreach copy [get_files -all -quiet *$name] {
        set path [file normalize [get_property NAME $copy]]
        if {[string trimright [read_text $path] "\n"] ne $expected} {error "Generated source differs: $path"}
        if {[string first /ipshared/ [string map {\\ /} $path]]>=0} {incr verified}
    }
    if {!$verified} {error "Missing regenerated source: $name"}
    puts "SNR_GENERATED_SOURCE_VERIFIED $name"
}
check_syntax -fileset sources_1
report_ip_status -file [file join $reports ip_status.rpt]
write_bd_tcl -force [file join $reports merged_system.tcl]
foreach run [get_runs -quiet *_synth_1] {reset_run $run}
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
file copy [file join $project AD9361_test2.srcs sources_1 bd System ip System_processing_system7_0_0 ps7_init.tcl] [file join $reports ps7_init.tcl]
file copy [file join $impl System_wrapper.bit] [file join $reports System_wrapper.bit]
puts "SNR_ORIGINAL_BUILD_COMPLETE $reports"
puts "Full legacy timing remains to be closed; inspect timing before board tests."
close_project
