#include <windows.h>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace fs = std::filesystem;

namespace {

// ============================================================================
// Game ABI structs & function pointers (Dirt Town Demo 0.1.0 ed45b4be7fc6)
// ============================================================================

struct GameStr {
    char* ptr;
    size_t size;
    union {
        char local[16];
        size_t cap;
    };
};

using FnOpNew = void* (*)(size_t);
using FnOpDelete = void (*)(void*, size_t);
using FnReadPackAsset = bool (*)(void* pack, const GameStr* key, GameStr* out);
using FnDrawFooterText = void (*)(const char* text);
using FnDrawSectionLabel = void (*)(const char* text);
using FnNextWidgetId = int (*)();
using FnDrawToggleBtn = bool (*)(const char* label, int id, int active, float scale, void* extra);
using FnSameLine = void (*)(float offset_x, float spacing);

constexpr uint32_t kPackHookCallRva = 0x0D1B087;
constexpr uint32_t kPackReadOrigRva = 0x0D16D30;
constexpr uint32_t kOpNewRva = 0x145E400;
constexpr uint32_t kOpDeleteRva = 0x145E3B0;

constexpr uint32_t kSettingsFooterCallRva = 0x0CB8C88;
constexpr uint32_t kSettingsFooterOrigRva = 0x0CBA150;
constexpr uint32_t kDrawSectionLabelRva = 0x116A430;
constexpr uint32_t kNextWidgetIdRva = 0x0CD86C0;
constexpr uint32_t kDrawToggleBtnRva = 0x0CDAD80;
constexpr uint32_t kSameLineRva = 0x114E600;

FnOpNew g_op_new = nullptr;
FnOpDelete g_op_delete = nullptr;
FnReadPackAsset g_orig_read_pack_asset = nullptr;
FnDrawFooterText g_orig_draw_footer = nullptr;
FnDrawSectionLabel g_draw_section_label = nullptr;
FnNextWidgetId g_next_widget_id = nullptr;
FnDrawToggleBtn g_draw_toggle_btn = nullptr;
FnSameLine g_same_line = nullptr;

// ============================================================================
// Plugin configuration, hot-swap state & pack override tables
// ============================================================================

enum class FontKind : uint8_t {
    Pack = 0,
    WinFont = 1,
};

struct FontRedirect {
    FontKind kind;
    std::string target;
};

struct TomlRule {
    std::string old_text;
    std::string new_text;
};

struct LocaleEntry {
    std::string code;
    std::string display_name;
};

struct SavedPatchSlice {
    uint32_t rva;
    std::vector<uint8_t> orig_bytes;
};

fs::path g_game_dir;
fs::path g_locales_root;
fs::path g_override_dir;
fs::path g_log_path;

std::string g_startup_lang = "en";
std::string g_active_lang = "en";
size_t g_active_index = 0;
std::vector<LocaleEntry> g_available_langs;

SRWLOCK g_pack_lock = SRWLOCK_INIT;
std::unordered_map<std::string, FontRedirect> g_font_redirects;
std::unordered_map<std::string, std::vector<TomlRule>> g_toml_rules;

// Saved original .text/.rdata bytes so we can cleanly revert & hot-swap locales in RAM
std::vector<SavedPatchSlice> g_saved_orig;
// Keep previous loc_mem buffers alive until process exit so in-flight frame pointers stay valid
std::vector<uint8_t*> g_alloc_loc_mems;

void LogMsg(const std::string& msg) {
    if (g_log_path.empty()) return;
    HANDLE h = CreateFileW(
        g_log_path.c_str(),
        FILE_APPEND_DATA,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        nullptr,
        OPEN_ALWAYS,
        FILE_ATTRIBUTE_NORMAL,
        nullptr);
    if (h == INVALID_HANDLE_VALUE) return;
    DWORD written = 0;
    WriteFile(h, msg.data(), static_cast<DWORD>(msg.size()), &written, nullptr);
    WriteFile(h, "\r\n", 2, &written, nullptr);
    CloseHandle(h);
}

bool ReadFileBytes(const fs::path& path, std::vector<uint8_t>& out) {
    HANDLE h = CreateFileW(
        path.c_str(),
        GENERIC_READ,
        FILE_SHARE_READ,
        nullptr,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    LARGE_INTEGER sz{};
    if (!GetFileSizeEx(h, &sz) || sz.QuadPart < 0 || sz.QuadPart > 256LL * 1024 * 1024) {
        CloseHandle(h);
        return false;
    }
    out.resize(static_cast<size_t>(sz.QuadPart));
    size_t off = 0;
    while (off < out.size()) {
        DWORD chunk = static_cast<DWORD>(std::min<size_t>(out.size() - off, 16 * 1024 * 1024));
        DWORD read = 0;
        if (!ReadFile(h, out.data() + off, chunk, &read, nullptr) || read == 0) {
            CloseHandle(h);
            return false;
        }
        off += read;
    }
    CloseHandle(h);
    return true;
}

std::string Trim(std::string_view sv) {
    while (!sv.empty() && (sv.front() == ' ' || sv.front() == '\t' || sv.front() == '\r' || sv.front() == '\n'))
        sv.remove_prefix(1);
    while (!sv.empty() && (sv.back() == ' ' || sv.back() == '\t' || sv.back() == '\r' || sv.back() == '\n'))
        sv.remove_suffix(1);
    return std::string(sv);
}

std::wstring Utf8ToWide(std::string_view sv) {
    if (sv.empty()) return {};
    int needed = MultiByteToWideChar(CP_UTF8, 0, sv.data(), static_cast<int>(sv.size()), nullptr, 0);
    if (needed <= 0) return {};
    std::wstring out(static_cast<size_t>(needed), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, sv.data(), static_cast<int>(sv.size()), out.data(), needed);
    return out;
}

fs::path Utf8ToPath(std::string_view sv) {
    return fs::path(Utf8ToWide(sv));
}

std::string ReadIniKey(const fs::path& ini_path, std::string_view key) {
    std::vector<uint8_t> raw;
    if (!ReadFileBytes(ini_path, raw)) return "";
    std::string_view text(reinterpret_cast<const char*>(raw.data()), raw.size());
    size_t pos = 0;
    while (pos < text.size()) {
        size_t nl = text.find('\n', pos);
        if (nl == std::string_view::npos) nl = text.size();
        std::string line = Trim(text.substr(pos, nl - pos));
        pos = nl + 1;
        if (line.empty() || line[0] == '#' || line[0] == ';') continue;
        size_t eq = line.find('=');
        if (eq == std::string::npos) continue;
        if (Trim(std::string_view(line).substr(0, eq)) == key) {
            return Trim(std::string_view(line).substr(eq + 1));
        }
    }
    return "";
}

bool WriteActiveLocale(const fs::path& ini_path, const std::string& code) {
    std::string content = "active=" + code + "\r\n";
    HANDLE h = CreateFileW(
        ini_path.c_str(),
        GENERIC_WRITE,
        FILE_SHARE_READ,
        nullptr,
        CREATE_ALWAYS,
        FILE_ATTRIBUTE_NORMAL,
        nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    DWORD written = 0;
    BOOL ok = WriteFile(h, content.data(), static_cast<DWORD>(content.size()), &written, nullptr);
    CloseHandle(h);
    return ok && written == content.size();
}

void DiscoverAvailableLocales() {
    g_available_langs.clear();
    g_available_langs.push_back(LocaleEntry{"en", "English"});
    std::error_code ec;
    std::vector<LocaleEntry> extra;
    for (const auto& entry : fs::directory_iterator(g_locales_root, ec)) {
        if (!entry.is_directory(ec)) continue;
        std::string code = entry.path().filename().string();
        if (code == "en" || code.empty() || code.size() > 15) continue;
        if (!fs::exists(entry.path() / L"exe_patch.dtloc", ec)) continue;

        std::string disp = ReadIniKey(entry.path() / L"meta.ini", "name");
        if (disp.empty()) {
            if (code == "ru") {
                disp = "\xD0\xA0\xD1\x83\xD1\x81\xD1\x81\xD0\xBA\xD0\xB8\xD0\xB9";  // Русский
            } else {
                disp = code;
                for (char& ch : disp) {
                    if (ch >= 'a' && ch <= 'z') ch = static_cast<char>(ch - 'a' + 'A');
                }
            }
        }
        // Keep button label safely under 31 UTF-8 bytes
        if (disp.size() > 30) {
            disp = code;
        }
        extra.push_back(LocaleEntry{std::move(code), std::move(disp)});
    }
    std::sort(extra.begin(), extra.end(), [](const LocaleEntry& a, const LocaleEntry& b) {
        return a.code < b.code;
    });
    for (auto& item : extra) {
        g_available_langs.push_back(std::move(item));
    }
}

void InitDefaultUnicodeFonts() {
    // Always preload Unicode/Cyrillic-capable font redirects so live EN <-> RU switching
    // renders properly without needing to rebuild the font atlas on restart.
    g_font_redirects["fonts/Roboto-Medium.ttf"] = FontRedirect{FontKind::Pack, "fonts/Roboto-Regular.ttf"};
    g_font_redirects["fonts/Roboto-Black.ttf"] = FontRedirect{FontKind::Pack, "fonts/Roboto-Bold.ttf"};
    g_font_redirects["fonts/CourierPrime-Regular.ttf"] = FontRedirect{FontKind::WinFont, "cour.ttf"};
    g_font_redirects["fonts/CourierPrime-Bold.ttf"] = FontRedirect{FontKind::WinFont, "courbd.ttf"};
}

// ============================================================================
// GameStr helpers (exact libstdc++ SSO ABI matching dirttown.exe)
// ============================================================================

void GameStrAssign(GameStr* s, const char* data, size_t len) {
    if (s->ptr != s->local) {
        g_op_delete(s->ptr, s->cap + 1);
    }
    if (len <= 15) {
        if (len > 0) std::memcpy(s->local, data, len);
        s->local[len] = '\0';
        s->ptr = s->local;
        s->size = len;
    } else {
        char* buf = static_cast<char*>(g_op_new(len + 1));
        std::memcpy(buf, data, len);
        buf[len] = '\0';
        s->ptr = buf;
        s->size = len;
        s->cap = len;
    }
}

void GameStrInitFrom(GameStr* s, std::string_view sv) {
    s->ptr = s->local;
    s->size = 0;
    s->local[0] = '\0';
    GameStrAssign(s, sv.data(), sv.size());
}

void GameStrFree(GameStr* s) {
    if (s->ptr != s->local) {
        g_op_delete(s->ptr, s->cap + 1);
        s->ptr = s->local;
        s->size = 0;
        s->local[0] = '\0';
    }
}

// ============================================================================
// Hook for DIGP pack asset reader (0x140d1b087 -> call 0x140d16d30)
// ============================================================================

std::string NormalizePackKey(std::string_view sv) {
    std::string out(sv);
    for (char& ch : out) {
        if (ch == '\\') ch = '/';
    }
    return out;
}

bool HookReadPackAsset(void* pack, const GameStr* key, GameStr* out) {
    if (!key || !key->ptr || !out) {
        return g_orig_read_pack_asset(pack, key, out);
    }

    std::string norm_key = NormalizePackKey(std::string_view(key->ptr, key->size));

    fs::path ov_dir;
    bool has_font = false;
    FontRedirect font_redir{};
    std::vector<TomlRule> rules;

    AcquireSRWLockShared(&g_pack_lock);
    ov_dir = g_override_dir;
    if (auto it = g_font_redirects.find(norm_key); it != g_font_redirects.end()) {
        has_font = true;
        font_redir = it->second;
    }
    if (auto it = g_toml_rules.find(norm_key); it != g_toml_rules.end()) {
        rules = it->second;
    }
    ReleaseSRWLockShared(&g_pack_lock);

    // 1. Loose file override in locales/<lang>/override/<key>
    if (!ov_dir.empty()) {
        fs::path ov_path = ov_dir / Utf8ToPath(norm_key);
        std::vector<uint8_t> bytes;
        if (ReadFileBytes(ov_path, bytes)) {
            GameStrAssign(out, reinterpret_cast<const char*>(bytes.data()), bytes.size());
            return true;
        }
    }

    // 2. Font redirect (pack entry redirect or system Windows font)
    if (has_font) {
        if (font_redir.kind == FontKind::WinFont) {
            wchar_t win_dir[MAX_PATH]{};
            if (GetWindowsDirectoryW(win_dir, MAX_PATH) > 0) {
                fs::path font_path = fs::path(win_dir) / L"Fonts" / Utf8ToPath(font_redir.target);
                std::vector<uint8_t> bytes;
                if (ReadFileBytes(font_path, bytes)) {
                    GameStrAssign(out, reinterpret_cast<const char*>(bytes.data()), bytes.size());
                    return true;
                }
            }
        } else if (font_redir.kind == FontKind::Pack) {
            GameStr alt_key{};
            GameStrInitFrom(&alt_key, font_redir.target);
            bool ok = g_orig_read_pack_asset(pack, &alt_key, out);
            GameStrFree(&alt_key);
            if (ok) return true;
        }
    }

    // 3. Read original asset from data.pack, then apply in-memory text rules
    bool ok = g_orig_read_pack_asset(pack, key, out);
    if (!ok || !out->ptr) return ok;

    if (!rules.empty()) {
        std::string text(out->ptr, out->size);
        bool modified = false;
        for (const auto& rule : rules) {
            size_t pos = 0;
            while ((pos = text.find(rule.old_text, pos)) != std::string::npos) {
                text.replace(pos, rule.old_text.size(), rule.new_text);
                pos += rule.new_text.size();
                modified = true;
            }
        }
        if (modified) {
            GameStrAssign(out, text.data(), text.size());
        }
    }

    return true;
}

// ============================================================================
// Binary reader & runtime PE memory patcher (with live hot-swap!)
// ============================================================================

class BinReader {
public:
    explicit BinReader(const std::vector<uint8_t>& buf) : buf_(buf) {}

    template <typename T>
    bool Read(T& out) {
        if (pos_ + sizeof(T) > buf_.size()) return false;
        std::memcpy(&out, buf_.data() + pos_, sizeof(T));
        pos_ += sizeof(T);
        return true;
    }

    bool ReadBytes(void* dst, size_t n) {
        if (pos_ + n > buf_.size()) return false;
        if (n > 0) std::memcpy(dst, buf_.data() + pos_, n);
        pos_ += n;
        return true;
    }

    bool ReadStr(size_t n, std::string& out) {
        if (pos_ + n > buf_.size()) return false;
        out.assign(reinterpret_cast<const char*>(buf_.data() + pos_), n);
        pos_ += n;
        return true;
    }

private:
    const std::vector<uint8_t>& buf_;
    size_t pos_ = 0;
};

#pragma pack(push, 1)
struct DtlpHeader {
    char magic[4];
    uint32_t version;
    uint32_t loc_blob_size;
    uint32_t rip32_count;
    uint32_t ptr64_count;
    uint32_t loc_ptr_count;
    uint32_t raw_count;
    uint32_t pack_hook_call_rva;
    uint32_t pack_read_orig_rva;
    uint32_t op_new_rva;
    uint32_t op_delete_rva;
};

struct Rip32Record {
    uint32_t insn_rva;
    uint32_t insn_size;
    int32_t expected_orig_disp;
    uint32_t target_loc_off;
};

struct Ptr64Record {
    uint32_t ptr_rva;
    uint32_t expected_orig_target_rva;
    uint32_t target_loc_off;
};

struct LocPtrRecord {
    uint32_t dst_loc_off;
    uint32_t target_loc_off;
};
#pragma pack(pop)

struct RawRecord {
    uint32_t rva;
    std::vector<uint8_t> expected_orig;
    std::vector<uint8_t> new_bytes;
};

uint8_t* AllocNearModule(uintptr_t base, size_t size) {
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return nullptr;
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return nullptr;

    uintptr_t img_end = (base + nt->OptionalHeader.SizeOfImage + 0xFFFFULL) & ~0xFFFFULL;
    const uintptr_t max_delta = 0x40000000ULL;

    for (uintptr_t addr = img_end; addr < base + max_delta; addr += 0x10000ULL) {
        void* p = VirtualAlloc(reinterpret_cast<void*>(addr), size, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
        if (p) return static_cast<uint8_t*>(p);
    }
    uintptr_t min_addr = (base > max_delta) ? (base - max_delta) : 0x10000ULL;
    uintptr_t start_down = (base & ~0xFFFFULL);
    for (uintptr_t addr = start_down; addr > min_addr; addr -= 0x10000ULL) {
        void* p = VirtualAlloc(reinterpret_cast<void*>(addr), size, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
        if (p) return static_cast<uint8_t*>(p);
    }
    return nullptr;
}

void WriteAbsJumpStub(uint8_t* stub, uint64_t fn_addr) {
    stub[0] = 0xFF;
    stub[1] = 0x25;
    uint32_t zero = 0;
    std::memcpy(stub + 2, &zero, 4);
    std::memcpy(stub + 6, &fn_addr, 8);
}

void PatchMemBytes(uintptr_t addr, const void* src, size_t sz) {
    DWORD oldp = 0;
    VirtualProtect(reinterpret_cast<void*>(addr), sz, PAGE_EXECUTE_READWRITE, &oldp);
    std::memcpy(reinterpret_cast<void*>(addr), src, sz);
    DWORD dummy = 0;
    VirtualProtect(reinterpret_cast<void*>(addr), sz, oldp, &dummy);
}

bool CanHookCallSite(uintptr_t base, size_t img_size, uint32_t call_rva, uint32_t orig_rva) {
    if (call_rva + 5 > img_size) return false;
    uint8_t op = *reinterpret_cast<uint8_t*>(base + call_rva);
    int32_t rel = 0;
    std::memcpy(&rel, reinterpret_cast<void*>(base + call_rva + 1), 4);
    return op == 0xE8 && static_cast<int64_t>(call_rva + 5) + rel == orig_rva;
}

void RevertExePatches(uintptr_t base, size_t img_size) {
    if (g_saved_orig.empty()) return;
    for (auto it = g_saved_orig.rbegin(); it != g_saved_orig.rend(); ++it) {
        PatchMemBytes(base + it->rva, it->orig_bytes.data(), it->orig_bytes.size());
    }
    g_saved_orig.clear();
    FlushInstructionCache(GetCurrentProcess(), reinterpret_cast<void*>(base), img_size);
}

bool LoadPackPatchesForLocale(const std::string& code) {
    std::unordered_map<std::string, FontRedirect> new_fonts;
    std::unordered_map<std::string, std::vector<TomlRule>> new_rules;
    fs::path new_ov_dir;

    // Always keep base Unicode fonts so switching EN <-> RU/etc. works live
    new_fonts["fonts/Roboto-Medium.ttf"] = FontRedirect{FontKind::Pack, "fonts/Roboto-Regular.ttf"};
    new_fonts["fonts/Roboto-Black.ttf"] = FontRedirect{FontKind::Pack, "fonts/Roboto-Bold.ttf"};
    new_fonts["fonts/CourierPrime-Regular.ttf"] = FontRedirect{FontKind::WinFont, "cour.ttf"};
    new_fonts["fonts/CourierPrime-Bold.ttf"] = FontRedirect{FontKind::WinFont, "courbd.ttf"};

    if (code != "en" && code != "none") {
        fs::path loc_dir = g_locales_root / Utf8ToPath(code);
        new_ov_dir = loc_dir / L"override";
        std::vector<uint8_t> buf;
        if (ReadFileBytes(loc_dir / L"pack_patches.dtpk", buf)) {
            BinReader r(buf);
            char magic[4]{};
            uint32_t ver = 0, font_cnt = 0, rule_cnt = 0;
            if (r.ReadBytes(magic, 4) && std::memcmp(magic, "DTPK", 4) == 0 &&
                r.Read(ver) && ver == 1 && r.Read(font_cnt) && r.Read(rule_cnt)) {
                bool ok = true;
                for (uint32_t i = 0; i < font_cnt && ok; ++i) {
                    uint16_t klen = 0, vlen = 0;
                    uint8_t kind = 0;
                    std::string k, v;
                    if (!r.Read(klen) || !r.ReadStr(klen, k) || !r.Read(kind) || !r.Read(vlen) || !r.ReadStr(vlen, v)) {
                        ok = false;
                        break;
                    }
                    new_fonts[k] = FontRedirect{static_cast<FontKind>(kind), std::move(v)};
                }
                for (uint32_t i = 0; i < rule_cnt && ok; ++i) {
                    uint16_t fklen = 0;
                    uint32_t olen = 0, nlen = 0;
                    std::string fk, old_s, new_s;
                    if (!r.Read(fklen) || !r.ReadStr(fklen, fk) ||
                        !r.Read(olen) || !r.ReadStr(olen, old_s) ||
                        !r.Read(nlen) || !r.ReadStr(nlen, new_s)) {
                        ok = false;
                        break;
                    }
                    new_rules[fk].push_back(TomlRule{std::move(old_s), std::move(new_s)});
                }
            }
        }
    }

    AcquireSRWLockExclusive(&g_pack_lock);
    g_override_dir = std::move(new_ov_dir);
    g_font_redirects = std::move(new_fonts);
    g_toml_rules = std::move(new_rules);
    ReleaseSRWLockExclusive(&g_pack_lock);
    return true;
}

bool ApplyExePatchesForLocale(const std::string& code) {
    uintptr_t base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return false;
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return false;
    size_t img_size = nt->OptionalHeader.SizeOfImage;

    // Always revert previous language patches back to pristine original bytes first
    RevertExePatches(base, img_size);

    if (code == "en" || code == "none") {
        LogMsg("Switched to English (original bytes restored).");
        return true;
    }

    fs::path dtlp_path = g_locales_root / Utf8ToPath(code) / L"exe_patch.dtloc";
    std::vector<uint8_t> buf;
    if (!ReadFileBytes(dtlp_path, buf)) {
        LogMsg("Failed to read exe_patch.dtloc for " + code);
        return false;
    }

    BinReader r(buf);
    DtlpHeader hdr{};
    if (!r.Read(hdr) || std::memcmp(hdr.magic, "DTLP", 4) != 0 || hdr.version != 1) {
        LogMsg("Invalid DTLP header.");
        return false;
    }

    std::vector<uint8_t> loc_blob(hdr.loc_blob_size);
    std::vector<Rip32Record> rip32s(hdr.rip32_count);
    std::vector<Ptr64Record> ptr64s(hdr.ptr64_count);
    std::vector<LocPtrRecord> loc_ptrs(hdr.loc_ptr_count);
    std::vector<RawRecord> raws(hdr.raw_count);

    if (!r.ReadBytes(loc_blob.data(), loc_blob.size()) ||
        !r.ReadBytes(rip32s.data(), rip32s.size() * sizeof(Rip32Record)) ||
        !r.ReadBytes(ptr64s.data(), ptr64s.size() * sizeof(Ptr64Record)) ||
        !r.ReadBytes(loc_ptrs.data(), loc_ptrs.size() * sizeof(LocPtrRecord))) {
        LogMsg("Truncated DTLP tables.");
        return false;
    }

    for (uint32_t i = 0; i < hdr.raw_count; ++i) {
        uint16_t sz = 0;
        if (!r.Read(raws[i].rva) || !r.Read(sz)) return false;
        raws[i].expected_orig.resize(sz);
        raws[i].new_bytes.resize(sz);
        if (!r.ReadBytes(raws[i].expected_orig.data(), sz) ||
            !r.ReadBytes(raws[i].new_bytes.data(), sz)) {
            return false;
        }
    }

    uint8_t* loc_mem = AllocNearModule(base, hdr.loc_blob_size);
    if (!loc_mem) {
        LogMsg("VirtualAlloc near module failed.");
        return false;
    }
    std::memcpy(loc_mem, loc_blob.data(), loc_blob.size());

    for (const auto& lp : loc_ptrs) {
        if (lp.dst_loc_off + 8 > hdr.loc_blob_size || lp.target_loc_off >= hdr.loc_blob_size) {
            VirtualFree(loc_mem, 0, MEM_RELEASE);
            return false;
        }
        uint64_t val = reinterpret_cast<uint64_t>(loc_mem + lp.target_loc_off);
        std::memcpy(loc_mem + lp.dst_loc_off, &val, sizeof(val));
    }

    // Validate all targets against pristine original bytes BEFORE modifying anything
    for (const auto& rp : rip32s) {
        if (rp.insn_rva + rp.insn_size > img_size || rp.target_loc_off >= hdr.loc_blob_size) {
            VirtualFree(loc_mem, 0, MEM_RELEASE);
            return false;
        }
        int32_t cur_disp = 0;
        std::memcpy(&cur_disp, reinterpret_cast<void*>(base + rp.insn_rva + rp.insn_size - 4), 4);
        if (cur_disp != rp.expected_orig_disp) {
            LogMsg("Build mismatch at RIP32 RVA " + std::to_string(rp.insn_rva));
            VirtualFree(loc_mem, 0, MEM_RELEASE);
            return false;
        }
        int64_t next_ip = static_cast<int64_t>(base + rp.insn_rva + rp.insn_size);
        int64_t new_disp = static_cast<int64_t>(reinterpret_cast<uintptr_t>(loc_mem + rp.target_loc_off)) - next_ip;
        if (new_disp < INT32_MIN || new_disp > INT32_MAX) {
            VirtualFree(loc_mem, 0, MEM_RELEASE);
            return false;
        }
    }

    for (const auto& pp : ptr64s) {
        if (pp.ptr_rva + 8 > img_size || pp.target_loc_off >= hdr.loc_blob_size) {
            VirtualFree(loc_mem, 0, MEM_RELEASE);
            return false;
        }
        uint64_t cur_val = 0;
        std::memcpy(&cur_val, reinterpret_cast<void*>(base + pp.ptr_rva), 8);
        if (cur_val != base + pp.expected_orig_target_rva) {
            LogMsg("Build mismatch at PTR64 RVA " + std::to_string(pp.ptr_rva));
            VirtualFree(loc_mem, 0, MEM_RELEASE);
            return false;
        }
    }

    for (const auto& rr : raws) {
        if (rr.rva + rr.expected_orig.size() > img_size) {
            VirtualFree(loc_mem, 0, MEM_RELEASE);
            return false;
        }
        if (std::memcmp(reinterpret_cast<void*>(base + rr.rva), rr.expected_orig.data(), rr.expected_orig.size()) != 0) {
            LogMsg("Build mismatch at RAW RVA " + std::to_string(rr.rva));
            VirtualFree(loc_mem, 0, MEM_RELEASE);
            return false;
        }
    }

    DWORD old_loc_prot = 0;
    VirtualProtect(loc_mem, hdr.loc_blob_size, PAGE_READONLY, &old_loc_prot);
    g_alloc_loc_mems.push_back(loc_mem);

    g_saved_orig.reserve(rip32s.size() + ptr64s.size() + raws.size());
    auto SaveAndPatch = [&](uint32_t rva, const void* new_src, size_t sz) {
        SavedPatchSlice slice;
        slice.rva = rva;
        slice.orig_bytes.resize(sz);
        std::memcpy(slice.orig_bytes.data(), reinterpret_cast<void*>(base + rva), sz);
        g_saved_orig.push_back(std::move(slice));
        PatchMemBytes(base + rva, new_src, sz);
    };

    for (const auto& rp : rip32s) {
        uint32_t disp_rva = rp.insn_rva + rp.insn_size - 4;
        int64_t next_ip = static_cast<int64_t>(base + rp.insn_rva + rp.insn_size);
        int32_t new_disp = static_cast<int32_t>(reinterpret_cast<uintptr_t>(loc_mem + rp.target_loc_off) - next_ip);
        SaveAndPatch(disp_rva, &new_disp, 4);
    }

    for (const auto& pp : ptr64s) {
        uint64_t val = reinterpret_cast<uint64_t>(loc_mem + pp.target_loc_off);
        SaveAndPatch(pp.ptr_rva, &val, 8);
    }

    for (const auto& rr : raws) {
        SaveAndPatch(rr.rva, rr.new_bytes.data(), rr.new_bytes.size());
    }

    FlushInstructionCache(GetCurrentProcess(), reinterpret_cast<void*>(base), img_size);
    LogMsg("Applied runtime locale cleanly: " + code);
    return true;
}

void SwitchLocaleLive(size_t new_index) {
    if (g_available_langs.empty()) return;
    new_index %= g_available_langs.size();
    const std::string& code = g_available_langs[new_index].code;
    g_active_index = new_index;
    g_active_lang = code;

    LoadPackPatchesForLocale(code);
    ApplyExePatchesForLocale(code);
    WriteActiveLocale(g_locales_root / L"lang.ini", code);
}

// ============================================================================
// In-game Settings carousel:  [ < ]  [ Русский ]  [ > ]
// ============================================================================

void HookDrawSettingsFooter(const char* version_str) {
    if (!g_available_langs.empty() && g_draw_section_label && g_next_widget_id && g_draw_toggle_btn && g_same_line) {
        const char* hdr = (g_active_lang == "en")
            ? "Language"
            : "\xD0\xAF\xD0\xB7\xD1\x8B\xD0\xBA / Language";  // Язык / Language
        g_draw_section_label(hdr);

        size_t n = g_available_langs.size();
        const std::string& cur_label = g_available_langs[g_active_index % n].display_name;

        int id_prev = g_next_widget_id();
        bool prev_clicked = g_draw_toggle_btn("<", id_prev, 0, 1.1f, nullptr);

        g_same_line(0.0f, -1.0f);
        int id_cur = g_next_widget_id();
        bool cur_clicked = g_draw_toggle_btn(cur_label.c_str(), id_cur, 1, 1.1f, nullptr);

        g_same_line(0.0f, -1.0f);
        int id_next = g_next_widget_id();
        bool next_clicked = g_draw_toggle_btn(">", id_next, 0, 1.1f, nullptr);

        if (n > 1) {
            if (prev_clicked) {
                SwitchLocaleLive((g_active_index + n - 1) % n);
            } else if (next_clicked || cur_clicked) {
                SwitchLocaleLive((g_active_index + 1) % n);
            }
        }

        if (g_active_lang != g_startup_lang && g_orig_draw_footer) {
            const char* note = (g_active_lang == "en")
                ? "Shop/map descriptions update on restart."
                : "\xD0\x9E\xD0\xBF\xD0\xB8\xD1\x81\xD0\xB0\xD0\xBD\xD0\xB8\xD1\x8F \xD1\x82\xD0\xB5\xD1\x85\xD0\xBD\xD0\xB8\xD0\xBA\xD0\xB8 \xD0\xBE\xD0\xB1\xD0\xBD\xD0\xBE\xD0\xB2\xD1\x8F\xD1\x82\xD1\x81\xD1\x8F \xD0\xBF\xD0\xBE\xD1\x81\xD0\xBB\xD0\xB5 \xD0\xBF\xD0\xB5\xD1\x80\xD0\xB5\xD0\xB7\xD0\xB0\xD0\xBF\xD1\x83\xD1\x81\xD0\xBA\xD0\xB0.";
            g_orig_draw_footer(note);
        }
    }
    if (g_orig_draw_footer) {
        g_orig_draw_footer(version_str);
    }
}

void InstallPermanentHooks() {
    uintptr_t base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return;
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return;
    size_t img_size = nt->OptionalHeader.SizeOfImage;

    bool has_pack = CanHookCallSite(base, img_size, kPackHookCallRva, kPackReadOrigRva);
    bool has_settings = CanHookCallSite(base, img_size, kSettingsFooterCallRva, kSettingsFooterOrigRva);
    if (!has_pack && !has_settings) return;

    uint8_t* stubs = AllocNearModule(base, 32);
    if (!stubs) return;

    if (has_pack) {
        WriteAbsJumpStub(stubs, reinterpret_cast<uint64_t>(&HookReadPackAsset));
    }
    if (has_settings) {
        WriteAbsJumpStub(stubs + 16, reinterpret_cast<uint64_t>(&HookDrawSettingsFooter));
    }

    DWORD oldp = 0;
    VirtualProtect(stubs, 32, PAGE_EXECUTE_READ, &oldp);
    FlushInstructionCache(GetCurrentProcess(), stubs, 32);

    if (has_pack) {
        g_op_new = reinterpret_cast<FnOpNew>(base + kOpNewRva);
        g_op_delete = reinterpret_cast<FnOpDelete>(base + kOpDeleteRva);
        g_orig_read_pack_asset = reinterpret_cast<FnReadPackAsset>(base + kPackReadOrigRva);

        int64_t next_ip = static_cast<int64_t>(base + kPackHookCallRva + 5);
        int32_t new_rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(stubs) - next_ip);
        PatchMemBytes(base + kPackHookCallRva + 1, &new_rel, 4);
    }

    if (has_settings) {
        g_orig_draw_footer = reinterpret_cast<FnDrawFooterText>(base + kSettingsFooterOrigRva);
        g_draw_section_label = reinterpret_cast<FnDrawSectionLabel>(base + kDrawSectionLabelRva);
        g_next_widget_id = reinterpret_cast<FnNextWidgetId>(base + kNextWidgetIdRva);
        g_draw_toggle_btn = reinterpret_cast<FnDrawToggleBtn>(base + kDrawToggleBtnRva);
        g_same_line = reinterpret_cast<FnSameLine>(base + kSameLineRva);

        int64_t next_ip = static_cast<int64_t>(base + kSettingsFooterCallRva + 5);
        int32_t new_rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(stubs + 16) - next_ip);
        PatchMemBytes(base + kSettingsFooterCallRva + 1, &new_rel, 4);
    }

    FlushInstructionCache(GetCurrentProcess(), reinterpret_cast<void*>(base), img_size);
}

void InitPlugin(HMODULE self_mod) {
    wchar_t mod_path[MAX_PATH]{};
    if (GetModuleFileNameW(self_mod, mod_path, MAX_PATH) == 0) return;

    g_game_dir = fs::path(mod_path).parent_path();
    g_locales_root = g_game_dir / L"locales";
    if (!fs::exists(g_locales_root)) return;

    g_log_path = g_locales_root / L"plugin.log";
    DeleteFileW(g_log_path.c_str());

    DiscoverAvailableLocales();
    std::string active = ReadIniKey(g_locales_root / L"lang.ini", "active");
    if (active.empty() || active == "none") active = "en";

    g_active_index = 0;
    for (size_t i = 0; i < g_available_langs.size(); ++i) {
        if (g_available_langs[i].code == active) {
            g_active_index = i;
            break;
        }
    }
    g_active_lang = g_available_langs[g_active_index].code;
    g_startup_lang = g_active_lang;

    InitDefaultUnicodeFonts();
    InstallPermanentHooks();
    LoadPackPatchesForLocale(g_active_lang);
    ApplyExePatchesForLocale(g_active_lang);
}

// ============================================================================
// Lazy forwarding to real %SystemRoot%\System32\version.dll
// ============================================================================

INIT_ONCE g_ver_once = INIT_ONCE_STATIC_INIT;
HMODULE g_real_version = nullptr;

BOOL CALLBACK LoadRealVersionCb(PINIT_ONCE, PVOID, PVOID*) {
    wchar_t sys_dir[MAX_PATH]{};
    if (GetSystemDirectoryW(sys_dir, MAX_PATH) > 0) {
        fs::path real_path = fs::path(sys_dir) / L"version.dll";
        g_real_version = LoadLibraryW(real_path.c_str());
    }
    return TRUE;
}

template <typename Fn>
Fn ResolveReal(const char* name) {
    InitOnceExecuteOnce(&g_ver_once, LoadRealVersionCb, nullptr, nullptr);
    if (!g_real_version) return nullptr;
    return reinterpret_cast<Fn>(GetProcAddress(g_real_version, name));
}

}  // namespace

extern "C" {

BOOL WINAPI Proxy_GetFileVersionInfoA(LPCSTR lptstrFilename, DWORD dwHandle, DWORD dwLen, LPVOID lpData) {
    auto fn = ResolveReal<decltype(&Proxy_GetFileVersionInfoA)>("GetFileVersionInfoA");
    return fn ? fn(lptstrFilename, dwHandle, dwLen, lpData) : FALSE;
}

BOOL WINAPI Proxy_GetFileVersionInfoExA(DWORD dwFlags, LPCSTR lpwstrFilename, DWORD dwHandle, DWORD dwLen, LPVOID lpData) {
    auto fn = ResolveReal<decltype(&Proxy_GetFileVersionInfoExA)>("GetFileVersionInfoExA");
    return fn ? fn(dwFlags, lpwstrFilename, dwHandle, dwLen, lpData) : FALSE;
}

BOOL WINAPI Proxy_GetFileVersionInfoExW(DWORD dwFlags, LPCWSTR lpwstrFilename, DWORD dwHandle, DWORD dwLen, LPVOID lpData) {
    auto fn = ResolveReal<decltype(&Proxy_GetFileVersionInfoExW)>("GetFileVersionInfoExW");
    return fn ? fn(dwFlags, lpwstrFilename, dwHandle, dwLen, lpData) : FALSE;
}

DWORD WINAPI Proxy_GetFileVersionInfoSizeA(LPCSTR lptstrFilename, LPDWORD lpdwHandle) {
    auto fn = ResolveReal<decltype(&Proxy_GetFileVersionInfoSizeA)>("GetFileVersionInfoSizeA");
    return fn ? fn(lptstrFilename, lpdwHandle) : 0;
}

DWORD WINAPI Proxy_GetFileVersionInfoSizeExA(DWORD dwFlags, LPCSTR lpwstrFilename, LPDWORD lpdwHandle) {
    auto fn = ResolveReal<decltype(&Proxy_GetFileVersionInfoSizeExA)>("GetFileVersionInfoSizeExA");
    return fn ? fn(dwFlags, lpwstrFilename, lpdwHandle) : 0;
}

DWORD WINAPI Proxy_GetFileVersionInfoSizeExW(DWORD dwFlags, LPCWSTR lpwstrFilename, LPDWORD lpdwHandle) {
    auto fn = ResolveReal<decltype(&Proxy_GetFileVersionInfoSizeExW)>("GetFileVersionInfoSizeExW");
    return fn ? fn(dwFlags, lpwstrFilename, lpdwHandle) : 0;
}

DWORD WINAPI Proxy_GetFileVersionInfoSizeW(LPCWSTR lptstrFilename, LPDWORD lpdwHandle) {
    auto fn = ResolveReal<decltype(&Proxy_GetFileVersionInfoSizeW)>("GetFileVersionInfoSizeW");
    return fn ? fn(lptstrFilename, lpdwHandle) : 0;
}

BOOL WINAPI Proxy_GetFileVersionInfoW(LPCWSTR lptstrFilename, DWORD dwHandle, DWORD dwLen, LPVOID lpData) {
    auto fn = ResolveReal<decltype(&Proxy_GetFileVersionInfoW)>("GetFileVersionInfoW");
    return fn ? fn(lptstrFilename, dwHandle, dwLen, lpData) : FALSE;
}

DWORD WINAPI Proxy_VerFindFileA(DWORD uFlags, LPCSTR szFileName, LPCSTR szWinDir, LPCSTR szAppDir, LPSTR szCurDir, PUINT puCurDirLen, LPSTR szDestDir, PUINT puDestDirLen) {
    auto fn = ResolveReal<decltype(&Proxy_VerFindFileA)>("VerFindFileA");
    return fn ? fn(uFlags, szFileName, szWinDir, szAppDir, szCurDir, puCurDirLen, szDestDir, puDestDirLen) : 0;
}

DWORD WINAPI Proxy_VerFindFileW(DWORD uFlags, LPCWSTR szFileName, LPCWSTR szWinDir, LPCWSTR szAppDir, LPWSTR szCurDir, PUINT puCurDirLen, LPWSTR szDestDir, PUINT puDestDirLen) {
    auto fn = ResolveReal<decltype(&Proxy_VerFindFileW)>("VerFindFileW");
    return fn ? fn(uFlags, szFileName, szWinDir, szAppDir, szCurDir, puCurDirLen, szDestDir, puDestDirLen) : 0;
}

DWORD WINAPI Proxy_VerInstallFileA(DWORD uFlags, LPCSTR szSrcFileName, LPCSTR szDestFileName, LPCSTR szSrcDir, LPCSTR szDestDir, LPCSTR szCurDir, LPSTR szTmpFile, PUINT puTmpFileLen) {
    auto fn = ResolveReal<decltype(&Proxy_VerInstallFileA)>("VerInstallFileA");
    return fn ? fn(uFlags, szSrcFileName, szDestFileName, szSrcDir, szDestDir, szCurDir, szTmpFile, puTmpFileLen) : 0;
}

DWORD WINAPI Proxy_VerInstallFileW(DWORD uFlags, LPCWSTR szSrcFileName, LPCWSTR szDestFileName, LPCWSTR szSrcDir, LPCWSTR szDestDir, LPCWSTR szCurDir, LPWSTR szTmpFile, PUINT puTmpFileLen) {
    auto fn = ResolveReal<decltype(&Proxy_VerInstallFileW)>("VerInstallFileW");
    return fn ? fn(uFlags, szSrcFileName, szDestFileName, szSrcDir, szDestDir, szCurDir, szTmpFile, puTmpFileLen) : 0;
}

DWORD WINAPI Proxy_VerLanguageNameA(DWORD wLang, LPSTR szLang, DWORD cchLang) {
    auto fn = ResolveReal<decltype(&Proxy_VerLanguageNameA)>("VerLanguageNameA");
    return fn ? fn(wLang, szLang, cchLang) : 0;
}

DWORD WINAPI Proxy_VerLanguageNameW(DWORD wLang, LPWSTR szLang, DWORD cchLang) {
    auto fn = ResolveReal<decltype(&Proxy_VerLanguageNameW)>("VerLanguageNameW");
    return fn ? fn(wLang, szLang, cchLang) : 0;
}

BOOL WINAPI Proxy_VerQueryValueA(LPCVOID pBlock, LPCSTR lpSubBlock, LPVOID* lplpBuffer, PUINT puLen) {
    auto fn = ResolveReal<decltype(&Proxy_VerQueryValueA)>("VerQueryValueA");
    return fn ? fn(pBlock, lpSubBlock, lplpBuffer, puLen) : FALSE;
}

BOOL WINAPI Proxy_VerQueryValueW(LPCVOID pBlock, LPCWSTR lpSubBlock, LPVOID* lplpBuffer, PUINT puLen) {
    auto fn = ResolveReal<decltype(&Proxy_VerQueryValueW)>("VerQueryValueW");
    return fn ? fn(pBlock, lpSubBlock, lplpBuffer, puLen) : FALSE;
}

}  // extern "C"

BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call, LPVOID) {
    if (ul_reason_for_call == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hModule);
        InitPlugin(hModule);
    } else if (ul_reason_for_call == DLL_PROCESS_DETACH) {
        for (uint8_t* p : g_alloc_loc_mems) {
            VirtualFree(p, 0, MEM_RELEASE);
        }
        g_alloc_loc_mems.clear();
        if (g_real_version) {
            FreeLibrary(g_real_version);
            g_real_version = nullptr;
        }
    }
    return TRUE;
}
