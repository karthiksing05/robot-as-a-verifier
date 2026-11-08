#!/bin/sh
# Draft 12 audio: Karthik's voiceover (FINAL_RAAV_AUDIO.m4a, 7.0 s after the cold open starts) over the music, which
# ducks under the voice; the take's room sound under the cold open and the close; the overhead clip's own arm sound,
# low, under the real run. Two-pass loudness to -16 LUFS, then mux with the silent render.
#   sh mix12.sh <silent.mp4> <out.mp4>
set -e
cd "$(dirname "$0")"
SILENT=${1:-../out/d12/silent.mp4}; OUT=${2:-../out/RAAV-draft12.mp4}; D=159.5
ffmpeg -v error -y -i ../real-world-assets/FINAL_RAAV_AUDIO.m4a -i ../out/music.wav -i ../real-world-assets/intro.MOV -i ../initial-vids/IMG_5920.MOV -filter_complex "\
[2:a]aresample=48000,atrim=0:11.3,asetpts=PTS-STARTPTS,atempo=1.79,afade=t=out:st=5.6:d=0.8,volume=6dB,apad=whole_dur=$D[roomA];\
[2:a]aresample=48000,atrim=11.5:24.5,asetpts=PTS-STARTPTS,afade=t=in:d=0.6,volume=6dB,adelay=147200|147200,apad=whole_dur=$D[roomB];\
[3:a]aresample=48000,atrim=18:104,asetpts=PTS-STARTPTS,atempo=2.0,volume=-14dB,afade=t=in:d=1,afade=t=out:st=41:d=2,adelay=19400|19400,apad=whole_dur=$D[arm];\
[0:a]aresample=48000,pan=stereo|c0=c0|c1=c0,adelay=7000|7000,apad=whole_dur=$D,highpass=f=70,acompressor=threshold=-20dB:ratio=3:attack=10:release=200,asplit=2[vo][key];\
[1:a]volume=-16dB,apad=whole_dur=$D[mus];\
[mus][key]sidechaincompress=threshold=0.03:ratio=6:attack=40:release=600[duck];\
[vo][duck][roomA][roomB][arm]amix=inputs=5:duration=first:normalize=0,atrim=0:$D[out]" -map "[out]" -ar 48000 ../out/premix12.wav
M=$(ffmpeg -nostats -i ../out/premix12.wav -af loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json -f null - 2>&1 | sed -n '/^{/,/^}/p')
get() { echo "$M" | grep "\"$1\"" | sed 's/.*: "\(.*\)".*/\1/'; }
ffmpeg -v error -y -i ../out/premix12.wav -af "loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=$(get input_i):measured_TP=$(get input_tp):measured_LRA=$(get input_lra):measured_thresh=$(get input_thresh):offset=$(get target_offset):linear=true" -ar 48000 ../out/mix12.wav
ffmpeg -v error -y -i "$SILENT" -i ../out/mix12.wav -c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart "$OUT"
echo "wrote $OUT"
