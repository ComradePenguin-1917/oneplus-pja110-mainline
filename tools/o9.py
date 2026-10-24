import json
p = r"H:\workspace\PJA110-Mainline\postmarketos\device\testing\device-oneplus-xigua\dtb-source\source-patches.json"
src = open(r"H:\workspace\PJA110-Mainline\postmarketos\device\testing\device-oneplus-xigua\dtb-source\oneplus-xigua.dts", encoding="utf-8").read()
j = json.load(open(p, encoding="utf-8"))

T3 = "\t\t\t"
T4 = "\t\t\t\t"

# 主补丁：usb@a600000 加 usb-role-switch，改 dr_mode 为 otg
old1 = (
 T4 + 'dma-coherent;\n'
 + T4 + 'phandle = <0x174>;\n'
 + T4 + 'maximum-speed = "high-speed";\n'
 + T4 + 'dr_mode = "peripheral";'
)
new1 = (
 T4 + 'dma-coherent;\n'
 + T4 + 'usb-role-switch;\n'
 + T4 + 'role-switch-default-mode = "peripheral";\n'
 + T4 + 'phandle = <0x174>;\n'
 + T4 + 'maximum-speed = "high-speed";\n'
 + T4 + 'dr_mode = "otg";'
)
assert src.count(old1) == 1, "anchor1 count=%d" % src.count(old1)
print("anchor1 OK")

j["replacements"].append({
    "old": old1,
    "new": new1,
    "node": "/soc@0/usb@a6f8800/usb@a600000 (dwc3)",
    "why": ("Enable dual-role USB. Upstream sm8550.dtsi has 'usb-role-switch;' and no dr_mode; "
            "our (vendor-derived) DTS hardcoded dr_mode=peripheral. dwc3 core.c would force "
            "otg back to peripheral when usb-role-switch is absent, so both must change together. "
            "role-switch-default-mode=peripheral keeps gadget mode at boot so the USB NCM debug "
            "channel stays alive until a role switch is explicitly requested.")
})

json.dump(j, open(p, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print("patch added, total:", len(j["replacements"]))
