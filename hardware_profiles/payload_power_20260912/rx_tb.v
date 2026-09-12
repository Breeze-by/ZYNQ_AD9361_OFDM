`timescale 1ns/1ps
module rx_tb;
localparam PAYLOAD_BYTES=128;
reg clock=0;
always #5 clock=~clock;
reg reset=1;
reg [31:0] sample_in=0;
reg stb=0;
reg [31:0] cfg=0;
reg [31:0] wave [0:40000];
reg [7:0] expected [0:PAYLOAD_BYTES-1];
wire header_ok,header_stb,byte_stb,fcs_stb,fcs_ok;
wire [7:0] byte_out,rate;
wire [15:0] length;
wire [4:0] state;
integer level,n,k,errors,bytes_seen,headers,fcs_pass,fd,rc;
integer channel_shift=3, wave_index=0, trace_fd, fft_fd;
integer max_level=4, fft_shift=4;
reg [31:0] sample_word;
dot11 dut(.clock(clock),.enable(1'b1),.reset(reset),.reset_without_watchdog(reset),
    .power_thres(11'd0),.min_plateau(32'd63),.threshold_scale(1'b0),
    .Fc_in_MHz(16'd2400),.rssi_half_db(11'd0),
    .sample_in(sample_in),.sample_in_strobe(stb),
    .soft_decoding(1'b1),.soft_bits_method(1'b0),.force_ht_smoothing(1'b1),
    .disable_all_smoothing(1'b0),.fft_win_shift(fft_shift[3:0]),.payload_power_config(cfg),
    .phase_offset_override_en(1'b0),.phase_offset_override_val(16'd0),
    .pkt_header_valid(header_ok),.pkt_header_valid_strobe(header_stb),
    .pkt_len(length),.pkt_rate(rate),.state(state),
    .byte_out(byte_out),.byte_out_strobe(byte_stb),
    .fcs_out_strobe(fcs_stb),.fcs_ok(fcs_ok));
always @(posedge clock) if(!reset) begin
    if(dut.sync_long_inst.fft_in_stb && dut.sync_long_inst.fft_ready && wave_index<550)
        $fdisplay(fft_fd,"%0d,%0d,%0d,%0d",level,wave_index,
            $signed(dut.sync_long_inst.fft_in_re_bitshift),$signed(dut.sync_long_inst.fft_in_im_bitshift));
    if(dut.short_preamble_detected || dut.long_preamble_detected)
        $display("STAGE17_RX_SYNC level=%0d sample=%0d short=%0d long=%0d",level,wave_index,dut.short_preamble_detected,dut.long_preamble_detected);
    if(dut.equalizer_out_strobe && dut.equalizer_inst.uep_eq_symbol<5)
        $fdisplay(trace_fd,"%0d,%0d,%0d,%0d,%0d,%0d",level,wave_index,state,dut.equalizer_inst.uep_eq_symbol,$signed(dut.eq_out_i),$signed(dut.eq_out_q));
    if(header_stb) begin
        $display("STAGE17_RX_HEADER level=%0d ok=%0d rate=%0h len=%0d signal=%06x status=%0d",level,header_ok,rate,length,dut.signal_bits,dut.status_code);
        if(header_ok && rate==8'h0b && length==PAYLOAD_BYTES+4) headers=headers+1;
        else $fatal(1,"Invalid PHY header in noiseless fixture");
    end
    // dot11 exposes SIGNAL/HT-SIG decoder bytes on this port as well.
    if(byte_stb && state==12) begin
        if(bytes_seen<PAYLOAD_BYTES && byte_out !== expected[bytes_seen]) begin
            errors=errors+1;
            if(errors<8) $display("STAGE17_RX_BAD level=%0d offset=%0d got=%02x want=%02x",level,bytes_seen,byte_out,expected[bytes_seen]);
        end
        bytes_seen=bytes_seen+1;
    end
    if(fcs_stb && fcs_ok) fcs_pass=fcs_pass+1;
end
initial begin
    rc=$value$plusargs("channel_shift=%d",channel_shift);
    rc=$value$plusargs("max_level=%d",max_level);
    rc=$value$plusargs("fft_shift=%d",fft_shift);
    $display("STAGE17_RX_FIXTURE channel_shift=%0d fft_shift=%0d max_level=%0d",channel_shift,fft_shift,max_level);
    trace_fd=$fopen("rx_eq_trace.csv","w");
    fft_fd=$fopen("rx_fft_trace.csv","w");
    $fdisplay(fft_fd,"level,sample,i,q");
    $fdisplay(trace_fd,"level,sample,state,symbol,i,q");
    $readmemh("payload.hex",expected);
    for(level=0;level<=max_level;level=level+1) begin
        reset=1; stb=0; sample_in=0;
        cfg=32'ha7008304|(level<<16); // 32 protected symbols, original low 10 bits.
        errors=0; bytes_seen=0; headers=0; fcs_pass=0;
        repeat(100) @(negedge clock);
        reset=0;
        repeat(100) @(negedge clock);
        for(n=0;n<400;n=n+1) begin
            sample_in=0; stb=1;
            @(negedge clock); stb=0;
            repeat(4) @(negedge clock);
        end
        fd=$fopen($sformatf("wave%0d.mem",level),"r");
        if(fd==0) $fatal(1,"Missing waveform");
        wave_index=0;
        while(!$feof(fd)) begin
            rc=$fscanf(fd,"%h\n",sample_word);
            if(rc==1) begin
                // Common channel attenuation keeps this fixture within a
                // signed 12-bit ADC range; relative TX power steps are unchanged.
                sample_in={$signed(sample_word[31:16]) >>> channel_shift,
                           $signed(sample_word[15:0]) >>> channel_shift}; stb=1;
                wave_index=wave_index+1;
                @(negedge clock); stb=0;
                repeat(4) @(negedge clock);
            end
        end
        $fclose(fd);
        // Zero-input tail maintains the sample cadence while pipelines drain.
        for(n=0;n<2000;n=n+1) begin
            sample_in=0; stb=1;
            @(negedge clock); stb=0;
            repeat(4) @(negedge clock);
        end
        $display("STAGE17_RX_RESULT level=%0d headers=%0d bytes=%0d errors=%0d fcs=%0d state=%0d",level,headers,bytes_seen,errors,fcs_pass,state);
        if(headers!=1 || bytes_seen!=PAYLOAD_BYTES+4 || errors!=0 || fcs_pass!=1)
            $fatal(1,"Noiseless end-to-end check failed");
    end
    $display("STAGE17_RX_SIM_COMPLETE");
    $fclose(trace_fd);
    $fclose(fft_fd);
    $finish;
end
initial begin #50000000; $fatal(1,"RX test timeout"); end
endmodule
