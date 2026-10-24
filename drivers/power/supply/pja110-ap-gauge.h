/* SPDX-License-Identifier: GPL-2.0-only */
/* Bring-up snapshot through the existing upstream BQ power_supply driver. */
static int pja110_ap_gauge_check(struct device *dev)
{
	struct power_supply *psy;
	union power_supply_propval v;
	int ret, voltage = 0, temperature = 0;

	psy = power_supply_get_by_name("bq28z610-0");
	if (!psy)
		return -EPROBE_DEFER;
	ret = power_supply_get_property(psy, POWER_SUPPLY_PROP_PRESENT, &v);
	if (ret || !v.intval) {
		ret = ret ? ret : -ENODEV;
		goto out;
	}
	ret = power_supply_get_property(psy, POWER_SUPPLY_PROP_HEALTH, &v);
	if (ret || v.intval != POWER_SUPPLY_HEALTH_GOOD) {
		ret = ret ? ret : -EPERM;
		goto out;
	}
	ret = power_supply_get_property(psy, POWER_SUPPLY_PROP_TEMP, &v);
	if (ret)
		goto out;
	temperature = v.intval;
	if (temperature < 100 || temperature > 400) {
		ret = -ERANGE;
		goto out;
	}
	ret = power_supply_get_property(psy, POWER_SUPPLY_PROP_VOLTAGE_NOW, &v);
	if (ret)
		goto out;
	voltage = v.intval;
	if (voltage < 6000000 || voltage > 8900000)
		ret = -ERANGE;
out:
	dev_info(dev, "PJA110 AP gauge check: ret=%d pack_uV=%d temp_dC=%d\n",
		 ret, voltage, temperature);
	power_supply_put(psy);
	return ret;
}
