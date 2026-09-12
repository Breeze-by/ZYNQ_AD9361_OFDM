# Isolated, backward-compatible extension: code 5 means DATA amplitude 3/64.
# Pair TX attenuation 13.5 dB with code 5 versus 16 dB / code 4 (1/16).
# Nominal weak-region RF power changes only +0.001225 dB; no added RF retry.
set here [file dirname [file normalize [info script]]]
if {$argc != 2} {error "Expected source project and NEW candidate directory"}
set source_project [file normalize [lindex $argv 0]]
set candidate_project [file normalize [lindex $argv 1]]
proc read_text {p} {set f [open $p r];fconfigure $f -encoding utf-8;set s [read $f];close $f;return $s}
proc write_text {p s} {set f [open $p w];fconfigure $f -encoding utf-8 -translation lf;puts -nonewline $f $s;close $f}
proc replace_once {s old new} {
    set a [string first $old $s]
    if {$a<0 || [string first $old $s [expr {$a+1}]]>=0} {error "Expected one anchor: $old"}
    return [string replace $s $a [expr {$a+[string length $old]-1}] $new]
}
proc patch_candidate {project} {
    global source_project
    if {[file normalize $project] eq $source_project} {error "Refuse original source"}
    set p [file join $project ip_repo openofdm_tx src payload_power_tx.vh]
    set s [read_text $p]
    set s [replace_once $s {uep_cfg[18:16] <= 4} {uep_cfg[18:16] <= 5}]
    set s [replace_once $s {    input [2:0] amount;
    begin} {    input [2:0] amount;
    reg signed [17:0] triple;
    begin
        triple = $signed({{2{value[15]}},value}) + ($signed({{2{value[15]}},value}) <<< 1);}]
    set s [replace_once $s {            default: uep_attenuate = value;} {            // Code 5 is 3/64, not 1/32; symmetric nearest rounding.
            5: uep_attenuate = {{4{triple[17]}},triple[17:6]} + (triple[5] & ((|triple[4:0]) | ~triple[17]));
            default: uep_attenuate = value;}]
    write_text $p $s
    set p [file join $project ip_repo openofdm_rx src payload_power_rx.vh]
    set s [read_text $p]
    set s [replace_once $s {uep_rx_cfg[18:16] <= 4} {uep_rx_cfg[18:16] <= 5}]
    set old {    reg signed [39:0] wide;
    begin
        wide = $signed({{8{value[31]}}, value}) <<< amount;
        if (wide > 40'sd32767) uep_restore = 16'h7fff;
        else if (wide < -40'sd32768) uep_restore = 16'h8000;
        else uep_restore = wide[15:0];}
    set new {    reg signed [39:0] wide;
    reg signed [27:0] fractional_product;
    begin
        // 21845/1024 approximates 64/3 with 15.3 ppm relative error.
        // Values outside this signed12 range saturate before truncation.
        fractional_product = $signed(value[11:0]) * 16'sd21845;
        wide = $signed({{8{value[31]}}, value}) <<< amount;
        if (amount == 5) begin
            wide = $signed(fractional_product) >>> 10;
            if (value > 32'sd1535) uep_restore = 16'h7fff;
            else if (value < -32'sd1536) uep_restore = 16'h8000;
            else uep_restore = wide[15:0];
        end else begin
            if (wide > 40'sd32767) uep_restore = 16'h7fff;
            else if (wide < -40'sd32768) uep_restore = 16'h8000;
            else uep_restore = wide[15:0];
        end}
    set s [replace_once $s $old $new]
    write_text $p $s
    set p [file join $project ip_repo openofdm_rx src demodulate.v]
    set s [read_text $p]
    set old {assign raw_llr_i_mult_csi_square_over_noise_var_reduce[0] = $signed(raw_llr_i_mult_csi_square_over_noise_var[0][(16+12+34):16]) >>> {power_shift_d3, 1'b0};}
    set new {// Code 5 has a^2=9/4096. Widen before shift/add to avoid wrapping.
wire signed [46:0] fractional_llr_input = $signed(raw_llr_i_mult_csi_square_over_noise_var[0][62:16]);
wire signed [50:0] fractional_llr_wide = {{4{fractional_llr_input[46]}},fractional_llr_input};
wire signed [50:0] fractional_llr_scaled = (fractional_llr_wide <<< 3) + fractional_llr_wide;
assign raw_llr_i_mult_csi_square_over_noise_var_reduce[0] = (power_shift_d3 == 5) ?
    (fractional_llr_scaled >>> 12) :
    ($signed(raw_llr_i_mult_csi_square_over_noise_var[0][(16+12+34):16]) >>> {power_shift_d3, 1'b0});}
    set s [replace_once $s $old $new]
    write_text $p $s
    # Original signature remains valid for codes 0..4; require the NEW capability
    # signature in both cores before code 5. Unused read addresses only.
    foreach {ip index op} {openofdm_tx 1F = openofdm_rx 1D <=} {
        set p [file join $project ip_repo $ip src ${ip}_s_axi.v]
        set s [read_text $p]
        set old "default : reg_data_out $op 0;"
        set new "5'h$index : reg_data_out $op 32'ha7200001;\n        $old"
        write_text $p [replace_once $s $old $new]
        set p [file join $project ip_repo $ip component.xml]
        set s [read_text $p]
        if {[regsub {<xilinx:coreRevision>118</xilinx:coreRevision>} $s {<xilinx:coreRevision>119</xilinx:coreRevision>} s]!=1} {error "Expected original IP revision118"}
        write_text $p $s
    }
    puts STAGE20_CANDIDATE_PATCHED
}
set template [read_text [file join $source_project AD9361_test2.sdk hardware_profiles sma_20260906 rebuild.tcl]]
set template [replace_once $template {# Rebase three packaged ROM initialization paths INSIDE the new build copy.} {patch_candidate $project
# Rebase three packaged ROM initialization paths INSIDE the new build copy.}]
set template [replace_once $template {open_bd_design $bd_file} {open_bd_design $bd_file
set changed_ips [concat [get_ips -quiet *openofdm_tx*] [get_ips -quiet *openofdm_rx*]]
if {[llength $changed_ips]!=2} {error "Expected two PHY IPs"}
upgrade_ip $changed_ips
}]
set argc 2
set argv [list $source_project $candidate_project]
if {[catch {eval $template} message options]} {
    puts stderr "STAGE20_BUILD_FAILED $message"
    puts stderr [dict get $options -errorinfo]
    exit 1
}
puts STAGE20_BUILD_COMPLETE
