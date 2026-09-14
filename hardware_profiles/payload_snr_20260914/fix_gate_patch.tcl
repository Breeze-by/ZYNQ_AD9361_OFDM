# Repair revision 122 only. Called on a backed-up project or isolated staging.
namespace eval snr_gate_fix {
    proc read_text {p} {set f [open $p r]; fconfigure $f -encoding utf-8; set s [read $f]; close $f; return $s}
    proc write_text {p s} {set f [open $p w]; fconfigure $f -encoding utf-8 -translation lf; puts -nonewline $f $s; close $f}
    proc once {s a b} {
        set n [string first $a $s]
        if {$n<0 || [string first $a $s [expr {$n+[string length $a]}]]>=0} {error "Gate anchor is not unique: $a"}
        return [string replace $s $n [expr {$n+[string length $a]-1}] $b]
    }
    proc patch {project} {
        set p [file join $project ip_repo openofdm_rx src dot11.v]
        set s [read_text $p]
        set s [once $s {reg snr_length_ready;
always @(posedge clock) begin
    if (reset || sync_long_reset) snr_length_ready <= 0;
    else if (phy_len_valid) snr_length_ready <= 1;
end} {reg snr_length_ready;
reg snr_packet_valid;
// Header-valid is a pulse: dot11 clears it on entry to S_DECODE_DATA.
// Retain the validated PHY type for this packet, never across RX recovery.
always @(posedge clock) begin
    if (reset || sync_long_reset || long_preamble_detected ||
        !sync_long_enable || fcs_out_strobe) begin
        snr_length_ready <= 0;
        snr_packet_valid <= 0;
    end else begin
        if (pkt_header_valid_strobe)
            snr_packet_valid <= pkt_header_valid && !pkt_ht && pkt_rate == 8'h0b;
        if (snr_packet_valid && phy_len_valid) snr_length_ready <= 1;
    end
end}]
        set s [once $s {    !pkt_ht && pkt_rate == 8'h0b && pkt_header_valid &&} {    snr_packet_valid && !reset && !sync_long_reset && !long_preamble_detected &&
    sync_long_enable && !fcs_out_strobe && !pkt_ht && pkt_rate == 8'h0b &&}]
        set xml [file join $project ip_repo openofdm_rx component.xml]
        set x [once [read_text $xml] {<xilinx:coreRevision>122</xilinx:coreRevision>} {<xilinx:coreRevision>123</xilinx:coreRevision>}]
        # Validate both anchors before writing either file.
        write_text $p $s
        write_text $xml $x
    }
}
