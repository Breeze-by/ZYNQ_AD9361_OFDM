# Vivado 2018.3: merge the tested D PHY into the original project and rebuild.
# Args: project-dir stage18-backup-dir NEW-report-dir git-executable
# Requires the user to save/close Vivado and SDK first. No board/Flash access.
if {$argc != 4} {error "Expected project, backup, NEW reports, git"}
if {![string match "2018.3*" [version -short]]} {error "Use Vivado 2018.3"}
lassign $argv project backup reports git
foreach name {project backup reports git} {set $name [file normalize [set $name]]}
set here [file dirname [file normalize [info script]]]
if {[file exists $reports]} {error "Refusing to overwrite reports: $reports"}
proc read_text {p} {set f [open $p r]; fconfigure $f -encoding utf-8; set s [read $f]; close $f; return $s}
proc write_text {p s} {set f [open $p w]; fconfigure $f -encoding utf-8 -translation lf; puts -nonewline $f $s; close $f}
set changed {
    openofdm_tx/src/openofdm_tx.v openofdm_tx/src/dot11_tx.v
    openofdm_rx/src/openofdm_rx.v openofdm_rx/src/dot11.v
    openofdm_rx/src/equalizer.v openofdm_rx/src/ofdm_decoder.v
    openofdm_rx/src/demodulate.v
}
set original_inputs {AD9361_test2.xpr AD9361_test2.srcs/sources_1/bd/System/System.bd}
foreach rel [concat $changed {openofdm_tx/component.xml openofdm_rx/component.xml}] {
    lappend original_inputs ip_repo/$rel
}
foreach rel $original_inputs {
    foreach root [list $project $backup] {
        if {![file isfile [file join $root $rel]]} {error "Missing input/backup: $root/$rel"}
    }
    if {[read_text [file join $project $rel]] ne [read_text [file join $backup $rel]]} {
        error "Original changed since backup; preserve user edits: $rel"
    }
}
foreach rel {openofdm_tx/src/payload_power_tx.vh openofdm_rx/src/payload_power_rx.vh} {
    if {[file exists [file join $project ip_repo $rel]]} {error "Already merged or unexpected header: $rel"}
}
file mkdir $reports
set staged [file join $reports staged]
foreach rel $changed {
    file mkdir [file dirname [file join $staged ip_repo $rel]]
    write_text [file join $staged ip_repo $rel] [read_text [file join $project ip_repo $rel]]
}
# Apply both dependent patches in staging before writing any original RTL.
foreach patch {experiment.patch llr_scale.patch} {
    set normalized [file join $reports $patch]
    write_text $normalized [read_text [file join $here $patch]]
    exec $git -C $staged apply --whitespace=nowarn --recount --unidiff-zero --check $normalized
    exec $git -C $staged apply --whitespace=nowarn --recount --unidiff-zero $normalized
}
foreach {ip header anchor} {openofdm_tx payload_power_tx.vh dot11_tx.v openofdm_rx payload_power_rx.vh equalizer.v} {
    file copy [file join $here $header] [file join $staged ip_repo $ip src $header]
    set xml [read_text [file join $project ip_repo $ip component.xml]]
    if {[string first stage5_diag $xml] >= 0} {error "Do not merge diagnostic interfaces"}
    if {[regsub {<xilinx:coreRevision>[0-9]+</xilinx:coreRevision>} $xml {<xilinx:coreRevision>118</xilinx:coreRevision>} xml] != 1} {error "IP revision missing"}
    set block "      <spirit:file>\n        <spirit:name>src/$anchor</spirit:name>"
    set extra "      <spirit:file>\n        <spirit:name>src/$header</spirit:name>\n        <spirit:fileType>verilogSource</spirit:fileType>\n        <spirit:isIncludeFile>true</spirit:isIncludeFile>\n      </spirit:file>\n$block"
    set updated [string map [list $block $extra] $xml]
    if {$updated eq $xml} {error "Missing IP file-group anchor"}
    write_text [file join $staged ip_repo $ip component.xml] $updated
}
set all_changed [concat $changed {
    openofdm_tx/src/payload_power_tx.vh openofdm_rx/src/payload_power_rx.vh
    openofdm_tx/component.xml openofdm_rx/component.xml
}]
foreach rel $all_changed {
    file copy -force [file join $staged ip_repo $rel] [file join $project ip_repo $rel]
}
puts STAGE18_ORIGINAL_RTL_MERGED
flush stdout
open_project [file join $project AD9361_test2.xpr]
set_property IP_REPO_PATHS [list [file join $project ip_repo]] [current_project]
update_ip_catalog -rebuild
set bd_file [file join $project AD9361_test2.srcs sources_1 bd System System.bd]
open_bd_design $bd_file
set ips [concat [get_ips -quiet *openofdm_tx*] [get_ips -quiet *openofdm_rx*]]
if {[llength $ips] != 2} {error "Expected TX and RX IP"}
upgrade_ip $ips
proc require_driver {destination source} {
    set net [get_bd_nets -quiet -of_objects [get_bd_pins $destination]]
    set drivers [get_bd_pins -quiet -of_objects $net -filter {DIR == O}]
    if {[llength $drivers] != 1 || [string trimleft [lindex $drivers 0] /] ne $source} {error "Unexpected driver at $destination: $drivers"}
}
foreach pin {tx_intf_0/dac_clk axis_data_fifo_3/s_axis_aclk rst_tx_transport/slowest_sync_clk} {require_driver $pin processing_system7_0/FCLK_CLK3}
foreach pin {rx_intf_0/adc_clk axis_data_fifo_4/m_axis_aclk rst_ps7_0_40M/slowest_sync_clk} {require_driver $pin processing_system7_0/FCLK_CLK2}
require_driver tx_intf_0/dac_rst rst_tx_transport/peripheral_reset
require_driver rx_intf_0/adc_rst rst_ps7_0_40M/peripheral_reset
set ps [get_bd_cells processing_system7_0]
foreach {index mhz} {0 100 1 200 2 40 3 41.666667} {
    if {abs([get_property CONFIG.PCW_FPGA${index}_PERIPHERAL_FREQMHZ $ps] - $mhz) > 0.001} {error "Unexpected FCLK$index"}
}
validate_bd_design
save_bd_design
set bd [get_files $bd_file]
reset_target all $bd
generate_target all $bd
export_ip_user_files -of_objects $bd -no_script -sync -force -quiet
update_compile_order -fileset sources_1
foreach rel [concat $changed {openofdm_tx/src/payload_power_tx.vh openofdm_rx/src/payload_power_rx.vh}] {
    set expected [string trimright [read_text [file join $project ip_repo $rel]] "\n"]
    set generated 0
    foreach copy [get_files -all -quiet *[file tail $rel]] {
        set path [file normalize [get_property NAME $copy]]
        if {[string trimright [read_text $path] "\n"] ne $expected} {error "Generated source mismatch: $path"}
        if {[string first /ipshared/ [string map {\\ /} $path]] >= 0} {incr generated}
    }
    if {$generated == 0} {error "No regenerated source verified: $rel"}
    puts "STAGE18_GENERATED_SOURCE_VERIFIED $rel"
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
foreach mhz {100 200 40 41.666667} {
    set selected {}
    foreach c [get_clocks] {if {abs([get_property PERIOD $c] - 1000.0/$mhz) < 0.001} {lappend selected $c}}
    if {![llength $selected]} {error "Expected clock domain missing: $mhz"}
    report_timing -from $selected -to $selected -delay_type min_max -max_paths 5 -file [file join $reports timing_${mhz}.rpt]
}
report_cdc -details -file [file join $reports cdc.rpt]
report_drc -file [file join $reports drc.rpt]
set impl [get_property DIRECTORY [get_runs impl_1]]
write_hwdef -force -file [file join $reports System_wrapper.hwdef]
write_sysdef -hwdef [file join $reports System_wrapper.hwdef] -bitfile [file join $impl System_wrapper.bit] -file [file join $reports System_wrapper.hdf]
write_debug_probes -force [file join $reports System_wrapper.ltx]
file copy [file join $project AD9361_test2.srcs sources_1 bd System ip System_processing_system7_0_0 ps7_init.tcl] [file join $reports ps7_init.tcl]
file copy [file join $impl System_wrapper.bit] [file join $reports System_wrapper.bit]
puts "STAGE18_BUILD_COMPLETE $reports"
puts "Inspect timing reports: bitstream generation does not imply full timing closure."
close_project
