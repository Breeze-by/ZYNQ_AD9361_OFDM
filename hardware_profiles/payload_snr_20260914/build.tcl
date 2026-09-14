# Isolated RX SNR instrument. Never edit the original project/SDK products.
if {$argc != 2} {error "Expected original project and NEW candidate directory"}
set here [file dirname [file normalize [info script]]]
set source_project [file normalize [lindex $argv 0]]
set candidate_project [file normalize [lindex $argv 1]]
proc read_text {p} {set f [open $p r];fconfigure $f -encoding utf-8;set s [read $f];close $f;return $s}
proc write_text {p s} {set f [open $p w];fconfigure $f -encoding utf-8 -translation lf;puts -nonewline $f $s;close $f}
proc once {s old new} {
    set a [string first $old $s]
    if {$a<0 || [string first $old $s [expr {$a+1}]]>=0} {error "Expected unique anchor: $old"}
    return [string replace $s $a [expr {$a+[string length $old]-1}] $new]
}
proc patch_candidate {project} {
    global source_project here
    if {[file normalize $project] eq $source_project} {error "Refuse original project"}
    set src [file join $project ip_repo openofdm_rx src]
    file copy [file join $here payload_snr_monitor.v] [file join $src payload_snr_monitor.v]
    set p [file join $src sync_long.v]
    set s [read_text $p]
    set s [once $s {    output reg [31:0] sample_out,} {    output wire [31:0] snr_iq,
    output wire snr_strobe,
    output reg [15:0] snr_symbol,
    output reg [31:0] sample_out,}]
    set s [once $s {reg raw_stb;} {reg raw_stb;
assign snr_iq = {raw_i, raw_q};
assign snr_strobe = raw_stb && !reset && enable;
// RAM output, raw_stb and this tag all correspond to the SAME read clock.
always @(posedge clock) begin
    if (reset) snr_symbol <= 0;
    else if (enable && (fft_start || fft_loading)) snr_symbol <= num_ofdm_symbol;
end}]
    write_text $p $s
    set p [file join $src dot11.v]
    set s [read_text $p]
    set s [once $s {    input [3:0] fft_win_shift,} {    input [3:0] fft_win_shift,
    output wire [31:0] snr_payload_iq,
    output wire snr_payload_strobe,}]
    set s [once $s {sync_long sync_long_inst (} {wire snr_raw_strobe;
wire [15:0] snr_raw_symbol;
reg snr_length_ready;
always @(posedge clock) begin
    if (reset || sync_long_reset) snr_length_ready <= 0;
    else if (phy_len_valid) snr_length_ready <= 1;
end
// LTF0, LTF1, SIGNAL2, DATA begins at 3. Omit an additional transition
// symbol after the protected prefix; measure only complete weak DATA windows.
assign snr_payload_strobe = snr_raw_strobe && snr_length_ready &&
    !pkt_ht && pkt_rate == 8'h0b && pkt_header_valid &&
    payload_power_config[31:24] == 8'ha7 && payload_power_config[18:16] <= 4 &&
    snr_raw_symbol >= (16'd4 + {10'd0,payload_power_config[15:10]}) &&
    snr_raw_symbol < (16'd3 + {1'b0,n_ofdm_sym});
sync_long sync_long_inst (}]
    set s [once $s {    .sample_out(sync_long_out),} {    .snr_iq(snr_payload_iq),
    .snr_strobe(snr_raw_strobe),
    .snr_symbol(snr_raw_symbol),
    .sample_out(sync_long_out),}]
    write_text $p $s
    set p [file join $src openofdm_rx.v]
    set s [read_text $p]
    set s [once $s {wire slv_reg_wren_signal;} {wire [31:0] snr_control, snr_read_data, snr_snapshot_seq;
wire [31:0] snr_payload_iq;
wire snr_payload_strobe;
payload_snr_monitor payload_snr_monitor_i (
    .clock(s00_axi_aclk), .reset(!s00_axi_aresetn || slv_reg0[0]),
    .control(snr_control), .phy_config(slv_reg5),
    .noise_iq(sample_in), .noise_strobe(sample_in_strobe),
    .payload_iq(snr_payload_iq), .payload_strobe(snr_payload_strobe),
    .valid_header(pkt_header_valid_strobe && pkt_header_valid),
    .snapshot_seq(snr_snapshot_seq), .read_data(snr_read_data)
);
wire slv_reg_wren_signal;}]
    set s [once $s {  .payload_power_config(slv_reg5),} {  .payload_power_config(slv_reg5),
  .snr_payload_iq(snr_payload_iq), .snr_payload_strobe(snr_payload_strobe),}]
    set s [once $s {  .SLV_REG0(slv_reg0),} {  .SNR_CONTROL(snr_control), .SNR_DATA(snr_read_data), .SNR_SEQ(snr_snapshot_seq),
  .SLV_REG0(slv_reg0),}]
    write_text $p $s
    set p [file join $src openofdm_rx_s_axi.v]
    set s [read_text $p]
    set s [once $s {  // Users to add ports here} {  output reg [31:0] SNR_CONTROL,
  input wire [31:0] SNR_DATA,
  input wire [31:0] SNR_SEQ,
  // Users to add ports here}]
    set s [once $s {  // Implement memory mapped register select and write logic generation} {  // Formerly unused config register 6, byte-write semantics preserved.
  integer snr_byte;
  always @(posedge S_AXI_ACLK) begin
    if (!S_AXI_ARESETN) SNR_CONTROL <= 0;
    else if (slv_reg_wren && axi_awaddr_core == 5'h06)
      for (snr_byte=0; snr_byte<4; snr_byte=snr_byte+1)
        if (S_AXI_WSTRB[snr_byte]) SNR_CONTROL[snr_byte*8 +: 8] <= S_AXI_WDATA[snr_byte*8 +: 8];
  end
  // Implement memory mapped register select and write logic generation}]
    set s [once $s {      default : reg_data_out <= 0;} {      5'h06   : reg_data_out <= SNR_CONTROL;
      5'h16   : reg_data_out <= SNR_SEQ;
      5'h1C   : reg_data_out <= SNR_DATA;
      5'h1D   : reg_data_out <= 32'ha7220001;
      default : reg_data_out <= 0;}]
    write_text $p $s
    set p [file join $project ip_repo openofdm_rx component.xml]
    set s [read_text $p]
    if {[regsub {<xilinx:coreRevision>118</xilinx:coreRevision>} $s {<xilinx:coreRevision>122</xilinx:coreRevision>} s]!=1} {error "Expected original RX revision 118"}
    set anchor "      <spirit:file>\n        <spirit:name>src/openofdm_rx.v</spirit:name>"
    set extra "      <spirit:file>\n        <spirit:name>src/payload_snr_monitor.v</spirit:name>\n        <spirit:fileType>verilogSource</spirit:fileType>\n      </spirit:file>\n$anchor"
    set updated [string map [list $anchor $extra] $s]
    if {$s eq $updated} {error "Missing IP file group"}
    write_text $p $updated
    source [file join $here fix_gate_patch.tcl]
    snr_gate_fix::patch $project
    puts SNR_CANDIDATE_PATCHED
}
set template [read_text [file join $source_project AD9361_test2.sdk hardware_profiles sma_20260906 rebuild.tcl]]
set template [once $template {# Rebase three packaged ROM initialization paths INSIDE the new build copy.} {patch_candidate $project
# Rebase three packaged ROM initialization paths INSIDE the new build copy.}]
set template [once $template {open_bd_design $bd_file} {open_bd_design $bd_file
set rx_ip [get_ips -quiet *openofdm_rx*]
if {[llength $rx_ip]!=1} {error "Expected one RX IP"}
upgrade_ip $rx_ip}]
set argv [list $source_project $candidate_project]
if {[catch {eval $template} msg opts]} {puts stderr "SNR_BUILD_FAILED $msg";puts stderr [dict get $opts -errorinfo];exit 1}
puts SNR_BUILD_COMPLETE
