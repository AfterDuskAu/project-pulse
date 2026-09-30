import AVFoundation
import Observation

/// Reads a briefing aloud with one of the Mac's own voices: nothing leaves the Mac. A British voice when the Mac
/// has one; the owner can pick another. One line at a time, so the screen can light up the line
/// being read.
@MainActor @Observable
final class Speaker: NSObject, AVSpeechSynthesizerDelegate {
    private let synthesizer = AVSpeechSynthesizer()
    private(set) var isSpeaking = false
    /// The line being read now (its id), and which briefing it belongs to ("home" or a project's slug).
    private(set) var current: String?
    private(set) var owner: String?
    private var lines: [ObjectIdentifier: String] = [:]
    private var last: ObjectIdentifier?

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    /// Reads the lines in order, or stops if this briefing is already being read.
    func toggle(_ spoken: [(id: String, text: String)], owner: String, voiceID: String) {
        if isSpeaking {
            let same = self.owner == owner
            stop()
            if same { return }
        }
        guard !spoken.isEmpty else { return }
        self.owner = owner
        lines = [:]
        let voice = Self.voice(id: voiceID)
        for line in spoken {
            let utterance = AVSpeechUtterance(string: line.text)
            utterance.voice = voice
            utterance.rate = AVSpeechUtteranceDefaultSpeechRate * 1.02
            utterance.postUtteranceDelay = 0.22
            lines[ObjectIdentifier(utterance)] = line.id
            last = ObjectIdentifier(utterance)
            synthesizer.speak(utterance)
        }
        isSpeaking = true
    }

    func stop() {
        synthesizer.stopSpeaking(at: .immediate)
        isSpeaking = false
        current = nil
        owner = nil
    }

    /// The English voices on this Mac, British first; the joke voices macOS ships are left out.
    static var englishVoices: [AVSpeechSynthesisVoice] {
        AVSpeechSynthesisVoice.speechVoices()
            .filter { $0.language.hasPrefix("en") && !novelty.contains($0.name) }
            .sorted { ($0.language != "en-GB" ? 1 : 0, $0.language, $0.name) < ($1.language != "en-GB" ? 1 : 0, $1.language, $1.name) }
    }

    /// The chosen voice; failing that a British man's voice (Arthur, then Daniel), then the Mac's own choice.
    static func voice(id: String) -> AVSpeechSynthesisVoice? {
        if !id.isEmpty, let chosen = AVSpeechSynthesisVoice(identifier: id) { return chosen }
        let voices = AVSpeechSynthesisVoice.speechVoices()
        for name in ["Arthur", "Daniel"] {
            if let voice = voices.first(where: { $0.language == "en-GB" && $0.name == name }) { return voice }
        }
        return voices.first { $0.language == "en-GB" } ?? AVSpeechSynthesisVoice(language: "en-GB")
    }

    private static let novelty: Set<String> = ["Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos",
                                                "Good News", "Jester", "Organ", "Superstar", "Trinoids", "Whisper",
                                                "Wobble", "Zarvox", "Grandma", "Grandpa", "Rocko", "Junior", "Ralph",
                                                "Fred", "Kathy"]

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didStart utterance: AVSpeechUtterance) {
        let started = ObjectIdentifier(utterance)
        Task { @MainActor in self.current = self.lines[started] }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        let finished = ObjectIdentifier(utterance)
        Task { @MainActor in
            if finished == self.last {
                self.isSpeaking = false
                self.current = nil
                self.owner = nil
            }
        }
    }
}
