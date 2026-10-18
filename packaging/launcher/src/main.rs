//! LOKI's double-click launcher (session 30, docs/SPEED.md "The Rust question").
//!
//! A ~200 KB native program that does one thing: start LOKI's bundled Python on the launcher
//! script, with no console window, as fast as the OS allows. It is `Loki.exe` in the Windows
//! installer and portable zip, and `Loki.app/Contents/MacOS/Loki` in the macOS app.
//!
//!   <root>/runtime/python/pythonw.exe (Windows) | <root>/runtime/python/bin/python3 (macOS/Linux)
//!   <root>/loki_launch.py --seed <root>/seed [args...]
//!
//! <root> is the folder of this program, or `Contents/Resources` inside a macOS .app. Without a
//! bundled runtime (a slim build) it runs the bootstrap instead, which downloads Python once.
//! It sets LOKI_LAUNCH_T0 (milliseconds since 1970 at the double click) so the app can log how long
//! the whole start took, and LOKI_INSTALL_DIR. Standard library only.
#![cfg_attr(windows, windows_subsystem = "windows")]

use std::env;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

fn root_dir() -> PathBuf {
    let exe = env::current_exe().unwrap_or_else(|_| PathBuf::from("."));
    let dir = exe.parent().map(Path::to_path_buf).unwrap_or_else(|| PathBuf::from("."));
    // macOS: Loki.app/Contents/MacOS/Loki -> Loki.app/Contents/Resources
    if dir.file_name().map(|n| n == "MacOS").unwrap_or(false) {
        if let Some(contents) = dir.parent() {
            let res = contents.join("Resources");
            if res.is_dir() {
                return res;
            }
        }
    }
    dir
}

fn bundled_python(root: &Path) -> Option<PathBuf> {
    let base = root.join("runtime").join("python");
    let candidates: Vec<PathBuf> = if cfg!(windows) {
        vec![base.join("pythonw.exe"), base.join("python.exe")]
    } else {
        vec![base.join("bin").join("python3"), base.join("bin").join("python")]
    };
    candidates.into_iter().find(|p| p.is_file())
}

#[cfg(windows)]
fn show_error(text: &str) {
    use std::os::windows::ffi::OsStrExt;
    #[link(name = "user32")]
    extern "system" {
        fn MessageBoxW(hwnd: *mut core::ffi::c_void, text: *const u16, caption: *const u16, kind: u32) -> i32;
    }
    let wide = |s: &str| -> Vec<u16> { std::ffi::OsStr::new(s).encode_wide().chain(std::iter::once(0)).collect() };
    let (t, c) = (wide(text), wide("LOKI"));
    unsafe {
        MessageBoxW(std::ptr::null_mut(), t.as_ptr(), c.as_ptr(), 0x10);
    }
}

#[cfg(not(windows))]
fn show_error(text: &str) {
    eprintln!("[loki] {}", text);
    if cfg!(target_os = "macos") {
        let script = format!("display alert \"LOKI\" message {:?}", text);
        let _ = Command::new("osascript").arg("-e").arg(script).status();
    }
}

fn command(root: &Path) -> Command {
    let args: Vec<String> = env::args().skip(1).filter(|a| !a.starts_with("-psn_")).collect(); // macOS adds -psn_ on old systems
    match bundled_python(root) {
        Some(python) => {
            let mut c = Command::new(python);
            c.arg(root.join("loki_launch.py")).arg("--seed").arg(root.join("seed")).args(&args);
            c
        }
        None if cfg!(windows) => {
            let mut c = Command::new("powershell.exe");
            c.args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File"])
                .arg(root.join("bootstrap.ps1"));
            c
        }
        None => {
            let mut c = Command::new("/bin/bash");
            c.arg(root.join("bootstrap.sh")).args(&args);
            c
        }
    }
}

fn main() {
    let t0 = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis()).unwrap_or(0);
    let root = root_dir();
    let mut cmd = command(&root);
    cmd.current_dir(&root).env("LOKI_LAUNCH_T0", t0.to_string()).env("LOKI_INSTALL_DIR", &root);
    if env::args().any(|a| a == "--print-command") {
        println!("{:?}", cmd);
        return;
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: no console, ever
        if let Err(e) = cmd.spawn() {
            show_error(&format!("LOKI could not start: {}\n\nReinstall LOKI, or see docs/TESTERS.md.", e));
            std::process::exit(1);
        }
    }
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        // become the Python process: macOS then ties the window and the Dock icon to Loki.app
        let e = cmd.exec();
        show_error(&format!("LOKI could not start: {}\n\nReinstall LOKI, or see docs/TESTERS.md.", e));
        std::process::exit(1);
    }
}
