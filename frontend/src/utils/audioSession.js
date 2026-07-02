/**
 * Declare a 'playback' audio session (Safari 16.4+ Audio Session API).
 *
 * On iOS, pure Web Audio output (AudioBufferSourceNode → destination) runs in
 * the default 'ambient' session, which the hardware mute switch silences —
 * unlike <audio> element playback. Any view that plays audio through a Web
 * Audio graph instead of a media element must declare 'playback' or iOS users
 * with the ringer off hear nothing (LiveFeed's decoded path and the detection
 * player's AudioBufferSourceNode transport both hit this).
 *
 * No-op on browsers without navigator.audioSession.
 */
export function declarePlaybackAudioSession() {
  try {
    if (navigator.audioSession) navigator.audioSession.type = 'playback'
  } catch { /* unsupported — degrade silently */ }
}
