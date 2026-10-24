import json
p = r"H:\workspace\PJA110-Mainline\postmarketos\device\testing\device-oneplus-xigua\dtb-source\source-patches.json"
j = json.load(open(p, encoding="utf-8"))

T4 = "\t\t\t\t"
T5 = "\t\t\t\t\t"

old = """\t\t\t\t\tvdd3-supply = <0xc9>;
\t\t\t\t\tphandle = <0xbe>;
\t\t\t\t};
\t\t\t};"""

new = """\t\t\t\t\tvdd3-supply = <0xc9>;
\t\t\t\t\tphandle = <0xbe>;
\t\t\t\t};

\t\t\t\thv-haptics@f000 {
\t\t\t\t\tcompatible = "qcom,hv-haptics";
\t\t\t\t\treg = <0xf000 0xf100 0xf200>;
\t\t\t\t\tinterrupts = <0x07 0xf0 0x01 0x01>;
\t\t\t\t\tinterrupt-names = "fifo-empty";
\t\t\t\t\tqcom,vmax-mv = <0x6b8>;
\t\t\t\t\tqcom,brake-mode = <0x00>;
\t\t\t\t\tqcom,brake-pattern = [ff 3f 1f];
\t\t\t\t\tqcom,lra-period-us = <0x1e0c>;
\t\t\t\t\tqcom,drv-sig-shape = <0x01>;
\t\t\t\t\tqcom,brake-sig-shape = <0x01>;
\t\t\t\t\tqcom,vibrator-type = <0x270f>;
\t\t\t\t\tstatus = "okay";
\t\t\t\t};
\t\t\t};"""

j["replacements"].append({
    "old": old,
    "new": new,
    "node": "/soc@0/spmi@c400000/pmic@7 (PM8550B) hv-haptics",
    "why": ("HV haptics node for the PM8550B (SPMI addr 0x07). Params copied from vendor DTB "
            "qcom,hv-haptics@f000: reg blocks at 0xf000/0xf100/0xf200, vmax 1720mV, "
            "LRA period 7692us, brake pattern ff 3f 1f, vibrator-type 9999 (LRA). "
            "Stage 1: node only + minimal params, to verify the SPMI driver can bind and read registers.")
})
json.dump(j, open(p, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print("patch added, total:", len(j["replacements"]))
