#!/bin/sh
# The cold open's own sound, then voice (delayed by the six-second cold open) over the music, which ducks under the voice; then mux with the silent render.
set -e
cd "$(dirname "$0")"
ffmpeg -v error -y -i ../real-world-assets/audioTrack.m4a -i ../out/music.wav -t 10.5 -i ../real-world-assets/intro.MOV -filter_complex "\
[2:a]aresample=48000,atempo=1.75,atrim=0:6,afade=t=out:st=5.2:d=0.8,volume=8dB,apad=whole_dur=194.6[room];\
[0:a]aresample=48000,pan=stereo|c0=c0|c1=c0,adelay=6000|6000,apad=whole_dur=194.6,highpass=f=70,acompressor=threshold=-20dB:ratio=3:attack=10:release=200,asplit=2[vo][key];\
[1:a]volume=-15dB[mus];\
[mus][key]sidechaincompress=threshold=0.03:ratio=6:attack=40:release=600[duck];\
[vo][duck][room]amix=inputs=3:duration=first:normalize=0[out]" -map "[out]" -ar 48000 ../out/premix.wav
# two-pass, linear loudness normalization, so quiet stretches stay quiet
M=$(ffmpeg -nostats -i ../out/premix.wav -af loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json -f null - 2>&1 | sed -n '/^{/,/^}/p')
get() { echo "$M" | grep "\"$1\"" | sed 's/.*: "\(.*\)".*/\1/'; }
ffmpeg -v error -y -i ../out/premix.wav -af "loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=$(get input_i):measured_TP=$(get input_tp):measured_LRA=$(get input_lra):measured_thresh=$(get input_thresh):offset=$(get target_offset):linear=true" -ar 48000 ../out/mix.wav
ffmpeg -v error -y -i ../out/silent.mp4 -i ../out/mix.wav -c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart ../out/RAAV-pitch.mp4
echo "wrote ../out/RAAV-pitch.mp4"
