# Isolated diagnostic build; never edits the user's source project.
# Args: source-project new-build-directory git-executable
set here [file dirname [file normalize [info script]]]
if {$argc != 3} {error "Expected source project, NEW build path, and git executable"}
set source_project [file normalize [lindex $argv 0]]
set candidate_project [file normalize [lindex $argv 1]]
set git [file normalize [lindex $argv 2]]
proc read_text {p} {set f [open $p r]; fconfigure $f -encoding utf-8; set s [read $f]; close $f; return $s}
proc write_text {p s} {set f [open $p w]; fconfigure $f -encoding utf-8 -translation lf; puts -nonewline $f $s; close $f}
proc replace_once {s old new} {
    set a [string first $old $s]
    if {$a < 0 || [string first $old $s [expr {$a+1}]] >= 0} {error "Expected exactly one template anchor: $old"}
    return [string replace $s $a [expr {$a+[string length $old]-1}] $new]
}
proc patch_candidate {project} {
    global here git source_project
    if {[file normalize $project] eq $source_project} {error "Refusing original project"}
    # Normalize only copied RTL so the portable LF patch also applies to a
    # CRLF Windows checkout; original source bytes remain untouched.
    foreach relative {openofdm_tx/src/openofdm_tx.v openofdm_tx/src/dot11_tx.v openofdm_rx/src/openofdm_rx.v openofdm_rx/src/dot11.v openofdm_rx/src/equalizer.v openofdm_rx/src/ofdm_decoder.v openofdm_rx/src/demodulate.v} {
        set path [file join $project ip_repo $relative]
        write_text $path [read_text $path]
    }
    exec $git -C $project apply --recount --unidiff-zero --check [file join $here experiment.patch]
    exec $git -C $project apply --recount --unidiff-zero [file join $here experiment.patch]
    exec $git -C $project apply --recount --unidiff-zero --check [file join $here llr_scale.patch]
    exec $git -C $project apply --recount --unidiff-zero [file join $here llr_scale.patch]
    foreach {ip header anchor} {openofdm_tx payload_power_tx.vh dot11_tx.v openofdm_rx payload_power_rx.vh equalizer.v} {
        file copy [file join $here $header] [file join $project ip_repo $ip src $header]
        set component [file join $project ip_repo $ip component.xml]
        set xml [read_text $component]
        if {[regsub {<xilinx:coreRevision>[0-9]+</xilinx:coreRevision>} $xml {<xilinx:coreRevision>118</xilinx:coreRevision>} xml] != 1} {error "IP revision missing"}
        set block "      <spirit:file>\n        <spirit:name>src/$anchor</spirit:name>"
        set extra "      <spirit:file>\n        <spirit:name>src/$header</spirit:name>\n        <spirit:fileType>verilogSource</spirit:fileType>\n        <spirit:isIncludeFile>true</spirit:isIncludeFile>\n      </spirit:file>\n$block"
        set count [llength [split $xml \n]]
        set changed [string map [list $block $extra] $xml]
        if {$changed eq $xml} {error "Missing IP file-group anchor"}
        write_text $component $changed
    }
    puts STAGE17_CANDIDATE_PATCHED
}
set template [read_text [file join $source_project AD9361_test2.sdk hardware_profiles sma_20260906 rebuild.tcl]]
set template [replace_once $template {# Rebase three packaged ROM initialization paths INSIDE the new build copy.} {patch_candidate $project
# Rebase three packaged ROM initialization paths INSIDE the new build copy.}]
set template [replace_once $template {open_bd_design $bd_file} {open_bd_design $bd_file
set changed_ips [concat [get_ips -quiet *openofdm_tx*] [get_ips -quiet *openofdm_rx*]]
if {[llength $changed_ips] != 2} {error "Expected TX and RX IP"}
upgrade_ip $changed_ips
}]
set argc 2
set argv [list $source_project $candidate_project]
if {[catch {eval $template} message options]} {
    puts stderr "STAGE17_BUILD_FAILED $message"
    puts stderr [dict get $options -errorinfo]
    exit 1
}
puts STAGE17_BUILD_COMPLETE
