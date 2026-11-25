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
// Game ABI structs & function pointers
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

FnOpNew g_op_new = nullptr;
FnOpDelete g_op_delete = nullptr;
FnReadPackAsset g_orig_read_pack_asset = nullptr;

// ============================================================================
// Plugin configuration & loaded override tables
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

fs::path g_game_dir;
fs::path g_locale_dir;
fs::path g_override_dir;
fs::path g_log_path;
std::unordered_map<std::string, FontRedirect> g_font_redirects;
std::unordered_map<std::string, std::vector<TomlRule>> g_toml_rules;

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

std::string ReadActiveLocale(const fs::path& ini_path) {
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
        if (Trim(std::string_view(line).substr(0, eq)) == "active") {
            return Trim(std::string_view(line).substr(eq + 1));
        }
    }
    return "";
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

    // 1. Loose file override in locales/<lang>/override/<key>
    if (!g_override_dir.empty()) {
        fs::path ov_path = g_override_dir / Utf8ToPath(norm_key);
        std::vector<uint8_t> bytes;
        if (ReadFileBytes(ov_path, bytes)) {
            GameStrAssign(out, reinterpret_cast<const char*>(bytes.data()), bytes.size());
            return true;
        }
    }

    // 2. Font redirect (pack entry redirect or system Windows font)
    if (auto it = g_font_redirects.find(norm_key); it != g_font_redirects.end()) {
        if (it->second.kind == FontKind::WinFont) {
            wchar_t win_dir[MAX_PATH]{};
            if (GetWindowsDirectoryW(win_dir, MAX_PATH) > 0) {
                fs::path font_path = fs::path(win_dir) / L"Fonts" / Utf8ToPath(it->second.target);
                std::vector<uint8_t> bytes;
                if (ReadFileBytes(font_path, bytes)) {
                    GameStrAssign(out, reinterpret_cast<const char*>(bytes.data()), bytes.size());
                    return true;
                }
            }
        } else if (it->second.kind == FontKind::Pack) {
            GameStr alt_key{};
            GameStrInitFrom(&alt_key, it->second.target);
            bool ok = g_orig_read_pack_asset(pack, &alt_key, out);
            GameStrFree(&alt_key);
            if (ok) return true;
        }
    }

    // 3. Read original asset from data.pack, then apply in-memory text rules
    bool ok = g_orig_read_pack_asset(pack, key, out);
    if (!ok || !out->ptr) return ok;

    if (auto it = g_toml_rules.find(norm_key); it != g_toml_rules.end()) {
        std::string text(out->ptr, out->size);
        bool modified = false;
        for (const auto& rule : it->second) {
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
// Binary reader & runtime PE memory patcher
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

    size_t Remaining() const { return buf_.size() - pos_; }

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

bool LoadPackPatches(const fs::path& dtpk_path) {
    std::vector<uint8_t> buf;
    if (!ReadFileBytes(dtpk_path, buf)) {
        LogMsg("No pack_patches.dtpk found (TOML/font patches skipped).");
        return true;
    }
    BinReader r(buf);
    char magic[4]{};
    uint32_t ver = 0, font_cnt = 0, rule_cnt = 0;
    if (!r.ReadBytes(magic, 4) || std::memcmp(magic, "DTPK", 4) != 0 ||
        !r.Read(ver) || ver != 1 || !r.Read(font_cnt) || !r.Read(rule_cnt)) {
        LogMsg("Invalid DTPK header.");
        return false;
    }
    for (uint32_t i = 0; i < font_cnt; ++i) {
        uint16_t klen = 0, vlen = 0;
        uint8_t kind = 0;
        std::string k, v;
        if (!r.Read(klen) || !r.ReadStr(klen, k) || !r.Read(kind) || !r.Read(vlen) || !r.ReadStr(vlen, v)) {
            LogMsg("Truncated DTPK font entry.");
            return false;
        }
        g_font_redirects[k] = FontRedirect{static_cast<FontKind>(kind), std::move(v)};
    }
    for (uint32_t i = 0; i < rule_cnt; ++i) {
        uint16_t fklen = 0;
        uint32_t olen = 0, nlen = 0;
        std::string fk, old_s, new_s;
        if (!r.Read(fklen) || !r.ReadStr(fklen, fk) ||
            !r.Read(olen) || !r.ReadStr(olen, old_s) ||
            !r.Read(nlen) || !r.ReadStr(nlen, new_s)) {
            LogMsg("Truncated DTPK rule entry.");
            return false;
        }
        g_toml_rules[fk].push_back(TomlRule{std::move(old_s), std::move(new_s)});
    }
    return true;
}

bool ApplyRuntimeExePatch(const fs::path& dtlp_path) {
    std::vector<uint8_t> buf;
    if (!ReadFileBytes(dtlp_path, buf)) {
        LogMsg("Failed to read exe_patch.dtloc");
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
        if (!r.Read(raws[i].rva) || !r.Read(sz)) {
            LogMsg("Truncated DTLP raw header.");
            return false;
        }
        raws[i].expected_orig.resize(sz);
        raws[i].new_bytes.resize(sz);
        if (!r.ReadBytes(raws[i].expected_orig.data(), sz) ||
            !r.ReadBytes(raws[i].new_bytes.data(), sz)) {
            LogMsg("Truncated DTLP raw payload.");
            return false;
        }
    }

    uintptr_t base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    size_t img_size = nt->OptionalHeader.SizeOfImage;

    // Allocate .loc + 16-byte trampoline stub within +-1 GB of dirttown.exe
    size_t stub_off = (hdr.loc_blob_size + 15ULL) & ~15ULL;
    size_t alloc_size = stub_off + 16ULL;
    uint8_t* loc_mem = AllocNearModule(base, alloc_size);
    if (!loc_mem) {
        LogMsg("VirtualAlloc near module failed.");
        return false;
    }

    std::memcpy(loc_mem, loc_blob.data(), loc_blob.size());

    // Pre-validate every target in RAM before patching ANY byte (build-mismatch safety)
    for (const auto& lp : loc_ptrs) {
        if (lp.dst_loc_off + 8 > hdr.loc_blob_size || lp.target_loc_off >= hdr.loc_blob_size) {
            LogMsg("Out-of-bounds loc_ptr offset.");
            VirtualFree(loc_mem, 0, MEM_RELEASE);
            return false;
        }
        uint64_t val = reinterpret_cast<uint64_t>(loc_mem + lp.target_loc_off);
        std::memcpy(loc_mem + lp.dst_loc_off, &val, sizeof(val));
    }

    for (const auto& rp : rip32s) {
        if (rp.insn_rva + rp.insn_size > img_size || rp.target_loc_off >= hdr.loc_blob_size) {
            LogMsg("Out-of-bounds rip32 record.");
            VirtualFree(loc_mem, 0, MEM_RELEASE);
            return false;
        }
        int32_t cur_disp = 0;
        std::memcpy(&cur_disp, reinterpret_cast<void*>(base + rp.insn_rva + rp.insn_size - 4), 4);
        if (cur_disp != rp.expected_orig_disp) {
            LogMsg("Build mismatch at RIP32 insn RVA " + std::to_string(rp.insn_rva));
            VirtualFree(loc_mem, 0, MEM_RELEASE);
            return false;
        }
        int64_t next_ip = static_cast<int64_t>(base + rp.insn_rva + rp.insn_size);
        int64_t new_disp = static_cast<int64_t>(reinterpret_cast<uintptr_t>(loc_mem + rp.target_loc_off)) - next_ip;
        if (new_disp < INT32_MIN || new_disp > INT32_MAX) {
            LogMsg("RIP32 disp out of range.");
            VirtualFree(loc_mem, 0, MEM_RELEASE);
            return false;
        }
    }

    for (const auto& pp : ptr64s) {
        if (pp.ptr_rva + 8 > img_size || pp.target_loc_off >= hdr.loc_blob_size) {
            LogMsg("Out-of-bounds ptr64 record.");
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
            LogMsg("Out-of-bounds raw record.");
            VirtualFree(loc_mem, 0, MEM_RELEASE);
            return false;
        }
        if (std::memcmp(reinterpret_cast<void*>(base + rr.rva), rr.expected_orig.data(), rr.expected_orig.size()) != 0) {
            LogMsg("Build mismatch at RAW RVA " + std::to_string(rr.rva));
            VirtualFree(loc_mem, 0, MEM_RELEASE);
            return false;
        }
    }

    // Validate pack hook call site (call rel32 -> orig_read_pack_asset)
    bool has_pack_hook = false;
    if (hdr.pack_hook_call_rva + 5 <= img_size) {
        uint8_t op = *reinterpret_cast<uint8_t*>(base + hdr.pack_hook_call_rva);
        int32_t rel = 0;
        std::memcpy(&rel, reinterpret_cast<void*>(base + hdr.pack_hook_call_rva + 1), 4);
        if (op == 0xE8 && static_cast<int64_t>(hdr.pack_hook_call_rva + 5) + rel == hdr.pack_read_orig_rva) {
            has_pack_hook = true;
        } else {
            LogMsg("Pack call site mismatch; skipping DIGP hook.");
        }
    }

    // Write 14-byte x64 absolute jump stub at loc_mem + stub_off: FF 25 00 00 00 00 <HookReadPackAsset>
    if (has_pack_hook) {
        uint8_t* stub = loc_mem + stub_off;
        stub[0] = 0xFF;
        stub[1] = 0x25;
        uint32_t zero = 0;
        std::memcpy(stub + 2, &zero, 4);
        uint64_t fn_addr = reinterpret_cast<uint64_t>(&HookReadPackAsset);
        std::memcpy(stub + 6, &fn_addr, 8);
    }

    DWORD old_loc_prot = 0;
    VirtualProtect(loc_mem, alloc_size, PAGE_EXECUTE_READ, &old_loc_prot);
    FlushInstructionCache(GetCurrentProcess(), loc_mem, alloc_size);

    // Apply validated patches in RAM
    auto PatchMem = [](uintptr_t addr, const void* src, size_t sz) {
        DWORD oldp = 0;
        VirtualProtect(reinterpret_cast<void*>(addr), sz, PAGE_EXECUTE_READWRITE, &oldp);
        std::memcpy(reinterpret_cast<void*>(addr), src, sz);
        DWORD dummy = 0;
        VirtualProtect(reinterpret_cast<void*>(addr), sz, oldp, &dummy);
    };

    for (const auto& rp : rip32s) {
        int64_t next_ip = static_cast<int64_t>(base + rp.insn_rva + rp.insn_size);
        int32_t new_disp = static_cast<int32_t>(reinterpret_cast<uintptr_t>(loc_mem + rp.target_loc_off) - next_ip);
        PatchMem(base + rp.insn_rva + rp.insn_size - 4, &new_disp, 4);
    }

    for (const auto& pp : ptr64s) {
        uint64_t val = reinterpret_cast<uint64_t>(loc_mem + pp.target_loc_off);
        PatchMem(base + pp.ptr_rva, &val, 8);
    }

    for (const auto& rr : raws) {
        PatchMem(base + rr.rva, rr.new_bytes.data(), rr.new_bytes.size());
    }

    if (has_pack_hook && (!g_font_redirects.empty() || !g_toml_rules.empty() || fs::exists(g_override_dir))) {
        g_op_new = reinterpret_cast<FnOpNew>(base + hdr.op_new_rva);
        g_op_delete = reinterpret_cast<FnOpDelete>(base + hdr.op_delete_rva);
        g_orig_read_pack_asset = reinterpret_cast<FnReadPackAsset>(base + hdr.pack_read_orig_rva);

        int64_t next_ip = static_cast<int64_t>(base + hdr.pack_hook_call_rva + 5);
        int32_t new_rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(loc_mem + stub_off) - next_ip);
        PatchMem(base + hdr.pack_hook_call_rva + 1, &new_rel, 4);
    }

    FlushInstructionCache(GetCurrentProcess(), reinterpret_cast<void*>(base), img_size);
    LogMsg("Applied runtime plugin cleanly.");
    return true;
}

void InitPlugin(HMODULE self_mod) {
    wchar_t mod_path[MAX_PATH]{};
    if (GetModuleFileNameW(self_mod, mod_path, MAX_PATH) == 0) return;

    g_game_dir = fs::path(mod_path).parent_path();
    fs::path locales_root = g_game_dir / L"locales";
    if (!fs::exists(locales_root)) return;

    g_log_path = locales_root / L"plugin.log";
    DeleteFileW(g_log_path.c_str());

    std::string active = ReadActiveLocale(locales_root / L"lang.ini");
    if (active.empty() || active == "en" || active == "none") {
        LogMsg("Plugin inactive (active=" + active + ").");
        return;
    }

    g_locale_dir = locales_root / Utf8ToPath(active);
    g_override_dir = g_locale_dir / L"override";
    if (!fs::exists(g_locale_dir)) {
        LogMsg("Locale folder missing: " + active);
        return;
    }

    LogMsg("Initializing locale: " + active);
    LoadPackPatches(g_locale_dir / L"pack_patches.dtpk");
    ApplyRuntimeExePatch(g_locale_dir / L"exe_patch.dtloc");
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
        if (g_real_version) {
            FreeLibrary(g_real_version);
            g_real_version = nullptr;
        }
    }
    return TRUE;
}
