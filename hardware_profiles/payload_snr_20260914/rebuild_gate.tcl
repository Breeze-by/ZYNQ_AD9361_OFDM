# Authorized original-project revision 122->123 repair, preserving RF/PS.
# Args: original project, verified full backup, NEW build-report directory.
if {$argc!=3} {error "Expected project backup reports"}
if {![string match "2018.3*" [version -short]]} {error "Use Vivado 2018.3"}
lassign $argv project backup reports
foreach n {project backup reports} {set $n [file normalize [set $n]]}
if {[file exists $reports]} {error "Preserve previous build"}
set profile [file dirname [file normalize [info script]]]
source [file join $profile fix_gate_patch.tcl]
proc read_text {p} {return [snr_gate_fix::read_text $p]}
set modified {sync_long.v dot11.v openofdm_rx.v openofdm_rx_s_axi.v}
set inputs {AD9361_test2.xpr AD9361_test2.srcs/sources_1/bd/System/System.bd ip_repo/openofdm_rx/component.xml}
foreach n [concat $modified {payload_snr_monitor.v}] {lappend inputs ip_repo/openofdm_rx/src/$n}
foreach rel $inputs {
    if {[read_text [file join $project $rel]] ne [read_text [file join $backup $rel]]} {error "Changed after backup: $rel"}
}
set code [read_text [file join $profile merge_into_project.tcl]]
set anchor {open_project [file join $project AD9361_test2.xpr]}
set a [string first $anchor $code]
if {$a<0} {error "Missing original build entry point"}
file mkdir [file join $reports staging ip_repo openofdm_rx src]
foreach rel {ip_repo/openofdm_rx/component.xml ip_repo/openofdm_rx/src/dot11.v} {
    file copy [file join $project $rel] [file join $reports staging $rel]
}
snr_gate_fix::patch [file join $reports staging]
foreach rel {ip_repo/openofdm_rx/component.xml ip_repo/openofdm_rx/src/dot11.v} {
    file copy -force [file join $reports staging $rel] [file join $project $rel]
}
puts SNR_GATE_ORIGINAL_PATCHED
# Reuse the original merge's checked IP upgrade, generated-source comparison,
# fixed clock guards, full implementation and matching export. No board access.
eval [string range $code $a end]
puts SNR_GATE_ORIGINAL_BUILD_COMPLETE
