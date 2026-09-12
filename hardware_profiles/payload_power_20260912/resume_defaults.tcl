# Retry implementation after a Vivado tool crash. No re-merge or RTL change.
# Args: original project directory, existing Stage 18 reports directory.
if {$argc != 2} {error "Expected project and reports"}
lassign $argv project reports
set project [file normalize $project]
set reports [file normalize $reports]
if {![file isdirectory $reports] || [file exists [file join $reports System_wrapper.hdf]]} {error "Expected incomplete Stage 18 build"}
set here [file dirname [file normalize [info script]]]
set f [open [file join $here merge_defaults.tcl] r]
set template [read $f]
close $f
set offset [string first "reset_run impl_1\n" $template]
if {$offset < 0} {error "Missing implementation template"}
foreach log [glob -nocomplain [file join $project AD9361_test2.runs impl_1 hs_err_pid*.log]] {
    file copy $log [file join $reports [file tail $log]]
}
open_project [file join $project AD9361_test2.xpr]
if {[get_property PROGRESS [get_runs synth_1]] ne {100%}} {error "Synthesis is not complete"}
puts "STAGE18_RETRY_IMPLEMENTATION_IDENTICAL_SETTINGS"
eval [string range $template $offset end]
