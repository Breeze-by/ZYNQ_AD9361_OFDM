`timescale 1ns/1ps
module llr_tb;
reg clock=0; always #5 clock=~clock;
reg enable=1,reset=1,stb=0;
reg signed [15:0] ci=0;
reg [2:0] shift=0;
wire [17:0] soft_out;
demodulate dut(.clock(clock),.enable(enable),.reset(reset),.rate(8'h0b),
    .cons_i(ci),.cons_q(16'sd0),.input_strobe(stb),.soft_bits_method(1'b0),
    .payload_power_shift(shift),.csi_square_over_noise_var_for_llr(34'sd8),
    .soft_bits(soft_out));
reg signed [63:0] expected[0:3];
integer n,j,checked=0;
reg [31:0] rnd=32'h19361320;
function [2:0] quant;
    input signed [63:0] x;
    begin
        if(x < -1239) quant=7;
        else if(x < -826) quant=6;
        else if(x < -413) quant=5;
        else if(x < 0) quant=4;
        else if(x < 413) quant=3;
        else if(x < 826) quant=2;
        else if(x < 1239) quant=1;
        else quant=0;
    end
endfunction
initial begin
    for(j=0;j<4;j=j+1) expected[j]=0;
    repeat(10) @(negedge clock);
    reset=0;
    for(n=0;n<4096;n=n+1) begin
        rnd={rnd[30:0],rnd[31]^rnd[21]^rnd[1]^rnd[0]};
        ci=rnd[15:0]; shift=n%5; stb=(n%3)!=0; enable=(n%13)!=0;
        @(posedge clock);
        if(enable) begin
            for(j=3;j>0;j=j-1) expected[j]=expected[j-1];
            expected[0]=(-64'sd4096*$signed(ci)*64'sd8) >>> (16+2*shift);
            checked=checked+1;
        end
        #1;
        if(checked>8) begin
            if($signed(dut.raw_llr_i_mult_csi_square_over_noise_var_reduce[0]) !== expected[2])
                $fatal(1,"LLR alignment n=%0d got=%0d want=%0d",n,$signed(dut.raw_llr_i_mult_csi_square_over_noise_var_reduce[0]),expected[2]);
            if(soft_out[2:0] !== quant(expected[3]))
                $fatal(1,"Soft quantization n=%0d got=%0d want=%0d",n,soft_out[2:0],quant(expected[3]));
        end
        @(negedge clock);
    end
    $display("STAGE17_LLR_UNIT_COMPLETE checked=%0d",checked);
    $finish;
end
endmodule
