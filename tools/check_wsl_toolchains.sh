#!/bin/bash
# Ordinary-user inspection and disposable ARM64 smoke test; no installs or sudo.
set -euo pipefail
printf 'PATH=%s\n' "$PATH"
for tool in aarch64-none-linux-gnu-gcc aarch64-none-linux-gnu-ld aarch64-linux-gnu-gcc aarch64-linux-gnu-gcc-14 aarch64-linux-gnu-gcc-13 aarch64-linux-gnu-g++ aarch64-linux-gnu-ld clang clang-20 ld.lld ld.lld-20 qemu-aarch64 qemu-aarch64-static qemu-system-aarch64 qemu-system-x86_64 qemu-img; do
 if command -v "$tool" >/dev/null 2>&1; then
  command -v "$tool"
  "$tool" --version | head -n 1
 else
  echo "MISSING: $tool"
 fi
done
echo '=== Installed compiler and emulator packages ==='
dpkg-query -W -f='${db:Status-Abbrev} ${binary:Package} ${Version}\n' '*aarch64*' 'qemu*' 'binfmt*' 'clang*' 'lld*' 2>/dev/null | awk '$1 == "ii"' || true
echo '=== ARM64 binfmt registration ==='
cat /proc/sys/fs/binfmt_misc/qemu-aarch64 || true
echo '=== KVM access ==='
if test -r /dev/kvm && test -w /dev/kvm; then echo KVM_ACCESS_OK; else echo KVM_NOT_ACCESSIBLE; fi
echo '=== ARM64 compile and execution smoke test ==='
probe_dir=$(mktemp -d /tmp/pja110-toolchain-check.XXXXXX)
trap 'rm -f -- "$probe_dir/hello.c" "$probe_dir/hello.S" "$probe_dir/hello.o" "$probe_dir/hello"; rmdir -- "$probe_dir"' EXIT
cat > "$probe_dir/hello.c" <<'EOF'
#include <stdio.h>
int main(void) { puts("ARM64_COMPILE_AND_RUN_PASS"); return 0; }
EOF
compiler=''
for candidate in aarch64-none-linux-gnu-gcc aarch64-linux-gnu-gcc; do
 if command -v "$candidate" >/dev/null; then compiler=$candidate; break; fi
done
if [ -n "$compiler" ]; then
 "$compiler" -dumpmachine
 "$compiler" -print-sysroot
 "$compiler" -static -O2 "$probe_dir/hello.c" -o "$probe_dir/hello"
 file "$probe_dir/hello"
 if command -v qemu-aarch64-static >/dev/null; then qemu-aarch64-static "$probe_dir/hello"; fi
 if test -r /proc/sys/fs/binfmt_misc/qemu-aarch64 && grep -q '^enabled' /proc/sys/fs/binfmt_misc/qemu-aarch64; then
  "$probe_dir/hello"
 fi
else
 echo 'Testing LLVM ARM64 assembler/linker without a C library.'
 cat > "$probe_dir/hello.S" <<'EOF'
.global _start
.text
_start:
 mov x0, #1
 adr x1, message
 mov x2, #message_end-message
 mov x8, #64
 svc #0
 mov x0, #0
 mov x8, #93
 svc #0
message:
 .ascii "ARM64_LLVM_AND_QEMU_PASS\n"
message_end:
EOF
 clang-20 --target=aarch64-linux-gnu -c "$probe_dir/hello.S" -o "$probe_dir/hello.o"
 ld.lld-20 -static -e _start "$probe_dir/hello.o" -o "$probe_dir/hello"
 file "$probe_dir/hello"
 qemu-aarch64-static "$probe_dir/hello"
 "$probe_dir/hello"
fi
if command -v qemu-system-aarch64 >/dev/null; then
 echo '=== ARM64 system emulator capabilities ==='
 qemu-system-aarch64 -machine help | grep -E '^virt[[:space:]-]' | head -n 4
 qemu-system-aarch64 -accel help
fi
