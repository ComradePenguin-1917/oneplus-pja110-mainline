import json
p = r"H:\workspace\PJA110-Mainline\postmarketos\device\testing\device-oneplus-xigua\dtb-source\source-patches.json"
src = open(r"H:\workspace\PJA110-Mainline\postmarketos\device\testing\device-oneplus-xigua\dtb-source\oneplus-xigua.dts", encoding="utf-8").read()
j = json.load(open(p, encoding="utf-8"))

T3 = "\t\t\t"
T4 = "\t\t\t\t"
T5 = "\t\t\t\t\t"

# 锚点: pmic@7 的 phy@fd00 节点之后（用 phy@fd00 的结尾做锚）
old = T4 + "phy@fd00 {\n" + T5 + 'compatible = "qcom,pm8550b-eusb2-repeater";'
assert src.count(old) == 1, "phy@fd00 anchor not unique: %d" % src.count(old)
print("anchor OK")
print("context:")
i = src.find(old)
print(src[i:i+400])
