import Foundation

/// "Good evening, sir." The briefing's first line, worked out when it's shown (not when Pulse last read the projects).
public enum Greeting {
    static let honorifics: Set<String> = ["sir", "ma'am", "madam", "boss", "chief", "captain"]

    /// What Pulse calls the owner when nothing was chosen: their first name, when the Mac knows a real one.
    public static func defaultName(fullName: String = NSFullUserName()) -> String {
        let first = fullName.split(separator: " ").first.map(String.init) ?? ""
        return first.count >= 2 && first.first?.isUppercase == true ? first : ""
    }

    public static func text(at date: Date, callMe: String, calendar: Calendar = .current) -> String {
        let hour = calendar.component(.hour, from: date)
        let part: String
        switch hour {
        case 5..<12: part = "Good morning"
        case 12..<18: part = "Good afternoon"
        default: part = "Good evening"
        }
        var name = callMe.trimmingCharacters(in: .whitespacesAndNewlines)
        if honorifics.contains(name.lowercased()) { name = name.lowercased() }  // "Good evening, sir."
        return name.isEmpty ? "\(part)." : "\(part), \(name)."
    }
}
