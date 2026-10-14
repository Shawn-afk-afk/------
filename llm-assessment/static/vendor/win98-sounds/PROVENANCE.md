# Windows 98 system WAV assets

Original WAV files downloaded on 2026-10-14 from https://lelegofrog.github.io/winwav98.html . Copyright belongs to Microsoft and its original contributors; this archive does not grant an open-source license to the sounds. They are separate from the application source license.

Original filenames and byte sizes match the archived Microsoft Windows 98 CD directory listing, KB Q188439: https://ftp.zx.net.nz/pub/archive/ftp.microsoft.com/MISC/KB/en-us/188/439.HTM . Size matches are provenance evidence, not Microsoft signatures. manifest.json records original URLs, SHA-256 hashes and audio properties.

start.wav uses Microsoft ADPCM (format 2), which browsers do not consistently support. start-pcm.wav is a decoded 16-bit PCM copy, preserving sample rate, channels and the original sound. Conversion: ffmpeg -i start.wav -c:a pcm_s16le start-pcm.wav . The original remains archived. All other playback WAVs are original PCM files. No synthesized or modern Windows substitutes are used. All playback is served locally, with no external asset requests.

The startup sound is an explicit preview only. Text entry, autosave and pen movement are silent.
