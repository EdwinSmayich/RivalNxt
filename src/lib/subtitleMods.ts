/**
 * Subtitle mods the Voice Subtitles tab makes ("RU Subtitles - Storm - Voice.zip").
 *
 * They are ordinary library downloads, but made on this computer: there is no
 * Nexus page, mod id or author to ask the user for. The tags are the backend's
 * LANGUAGE_TAGS (core/voice_subtitles/game.py).
 */
const TAGS = ["EN", "RU", "DE", "FR", "ES", "LAS", "IT", "PL", "PT", "TR", "JA", "KO", "CHS", "CHT", "TH", "AR", "ID", "VI"];
// As made ("RU Subtitles - ..."), or as the library stores an added file ("RU_Subtitles_-_...").
const ARCHIVE = new RegExp(`(^|[\\\\/])(${TAGS.join("|")})[ _]Subtitles[ _]-[ _][^\\\\/]+\\.zip$`, "i");

export function isSubtitleModArchive(path: string | null | undefined): boolean {
  return !!path && ARCHIVE.test(path);
}
