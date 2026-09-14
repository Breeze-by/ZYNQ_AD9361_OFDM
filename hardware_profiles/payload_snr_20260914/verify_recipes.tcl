# Verify both reproducible recipes against current original sources, no build/JTAG.
# Args: current project, revision122 backup, revision118 backup, NEW output.
if {$argc!=4} {error "Expected current before122 before118 out"}
lassign $argv current before122 before118 out
if {[file exists $out]} {error "Preserve previous recipe evidence"}
set here [file dirname [file normalize [info script]]]
source [file join $here fix_gate_patch.tcl]
set names {sync_long.v dot11.v openofdm_rx.v openofdm_rx_s_axi.v}
foreach {name baseline} [list gate $before122 candidate $before118] {
    set dest [file join $out $name]
    file mkdir [file join $dest ip_repo openofdm_rx src]
    file copy [file join $baseline ip_repo openofdm_rx component.xml] [file join $dest ip_repo openofdm_rx component.xml]
    foreach n $names {file copy [file join $baseline ip_repo openofdm_rx src $n] [file join $dest ip_repo openofdm_rx src $n]}
}
snr_gate_fix::patch [file join $out gate]
set text [snr_gate_fix::read_text [file join $here build.tcl]]
set start [string first {proc read_text} $text]
set end [string first {set template [read_text} $text]
if {$start<0 || $end<=$start} {error "Missing candidate recipe entry"}
eval [string range $text $start [expr {$end-1}]]
set source_project [file normalize $current]
patch_candidate [file join $out candidate]
foreach stage {gate candidate} {
    set check {ip_repo/openofdm_rx/component.xml ip_repo/openofdm_rx/src/dot11.v}
    if {$stage eq "candidate"} {
        foreach n {sync_long.v openofdm_rx.v openofdm_rx_s_axi.v payload_snr_monitor.v} {lappend check ip_repo/openofdm_rx/src/$n}
    }
    foreach rel $check {
        if {[string trimright [read_text [file join $current $rel]]] ne [string trimright [read_text [file join $out $stage $rel]]]} {error "Recipe mismatch: $stage/$rel"}
        puts "SNR_RECIPE_VERIFIED $stage/$rel"
    }
}
puts SNR_RECIPES_COMPLETE
