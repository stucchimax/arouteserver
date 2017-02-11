# Copyright (C) 2017 Pier Carlo Chiodi
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import ipaddr
import yaml


from ..errors import ConfigError


class ConfigParserValidator(object):

    def __init__(self, **kwargs):
        self.mandatory = True
        if "mandatory" in kwargs:
            self.mandatory = bool(kwargs["mandatory"])

        self.default = None
        if "default" in kwargs:
            self.default = kwargs["default"]

    def _validate(self, v):
        raise NotImplementedError()

    def validate(self, v):
        try:
            if v is None:
                if self.mandatory:
                    if self.default is not None:
                        return self._validate(self.default)
                    raise ConfigError()
                else:
                    return None

            if isinstance(v, str):
                if v.strip() == "":
                    if self.mandatory:
                        if self.default is not None:
                            return self._validate(self.default)
                        raise ConfigError()
                    else:
                        return None

        except ConfigError:
            raise ConfigError("Can't be empty")

        return self._validate(v)

class ValidatorUInt(ConfigParserValidator):

    def _validate(self, v):
        if isinstance(v, str):
            if v.strip().isdigit():
                return int(v)
            else:
                raise ConfigError()
        if isinstance(v, int):
            if v >= 0:
                return v
            else:
                raise ConfigError()
        raise ConfigError()

class ValidatorText(ConfigParserValidator):

    def _validate(self, v):
        if v is not None:
            return str(v)
        return None

class ValidatorASSet(ValidatorText):
    pass

class ValidatorASN(ConfigParserValidator):

    def _validate(self, v):
        try:
            asn = ValidatorUInt().validate(v)
            if asn == 0:
                raise ConfigError()
            return asn
        except ConfigError:
            raise ConfigError("Invalid ASN: {}".format(v))

class ValidatorASNList(ConfigParserValidator):

    def _validate(self, v):
        if isinstance(v, str):
            parts = v.split(",")
        elif isinstance(v, list):
            parts = v
        elif isinstance(v, int):
            return [ValidatorASN().validate(v)]
        else:
            raise ConfigError(
                "Invalid format: must be a list or a "
                "comma-separated list of ASNs"
            )

        asns = []
        for part in parts:
            asns.append(ValidatorASN().validate(part))
        return asns

class ValidatorROA(ConfigParserValidator):

    def _validate(self, v):
        for prop in v:
            if prop not in ("prefix", "asn"):
                raise ConfigError(
                    "Unknown statement '{}' in ROA entry "
                    "definition".format(prop)
                )
        for prop in ("prefix", "asn"):
            if prop not in v:
                raise ConfigError(
                    "Missing '{}' in ROA entry".format(prop)
                )
        try:
            asn = ValidatorASN().validate(v["asn"])
        except ConfigError as e:
            err_msg = "Invalid ASN in ROA entry"
            if str(e):
                err_msg += ": {}".format(str(e))
            raise ConfigError(err_msg)

        try:
            prefix = ValidatorPrefixListEntry().validate(v["prefix"])
        except ConfigError as e:
            err_msg = "Invalid prefix in ROA entry"
            if str(e):
                err_msg += ": {}".format(str(e))
            raise ConfigError(err_msg)

        if prefix["ge"] and prefix["ge"] != prefix["length"]:
            raise ConfigError(
                "ROA prefix 'ge' must be equal to the "
                "prefix length: {} != {} for prefix {}".format(
                    prefix["ge"], prefix["length"], prefix["prefix"]
                )
            )
        if not prefix["le"]:
            prefix["exact"] = True

        return {"asn": asn, "prefix": prefix}

class ValidatorIPAddr(ConfigParserValidator):

    def _validate(self, v):
        try:
            ip = ipaddr.IPAddress(v)
            return str(ip)
        except:
            raise ConfigError("Invalid IP address: {}".format(v))

class ValidatorIPv4Addr(ConfigParserValidator):

    def _validate(self, v):
        try:
            ip = ipaddr.IPv4Address(v)
            return str(ip)
        except:
            raise ConfigError("Invalid IPv4 address: {}".format(v))

class ValidatorIPv6Addr(ConfigParserValidator):

    def _validate(self, v):
        try:
            ip = ipaddr.IPv6Address(v)
            return str(ip)
        except:
            raise ConfigError("Invalid IPv6 address: {}".format(v))

class ValidatorListOf(ConfigParserValidator):

    def __init__(self, cls, *args, **kwargs):
        ConfigParserValidator.__init__(self, *args, **kwargs)
        self.cls = cls

    def _validate(self, l):
        if not isinstance(l, list):
            raise ConfigError("Invalid format: must be a list")

        for v in l:
            validator = self.cls()
            v = validator.validate(v)

        return l

class ValidatorPrefixListEntry(ConfigParserValidator):

    def _validate(self, v):
        if not isinstance(v, dict):
            raise ConfigError("Invalid prefix list entry format: must be dict")

        for prop in v:
            if prop not in ("prefix", "length", "comment", "exact", "ge", "le",
                            "max_length"):
                raise ConfigError(
                    "Unknown statement '{}' in prefix list entry "
                    "definition".format(prop)
                )
        for prop in ("prefix", "length"):
            if prop not in v:
                raise ConfigError(
                    "Missing '{}' in prefix list entry".format(prop)
                )

        try:
            ip_obj = ipaddr.IPAddress(v["prefix"])
        except:
            raise ConfigError("Invalid prefix ID: {}".format(v["prefix"]))

        try:
            pref_len = ValidatorUInt().validate(v["length"])

            if pref_len < 0:
                raise ConfigError()
            if ip_obj.version == 4:
                if pref_len > 32:
                    raise ConfigError()
            if ip_obj.version == 6:
                if pref_len > 128:
                    raise ConfigError()
        except:
            raise ConfigError("Invalid prefix length: {}".format(v["length"]))

        v["prefix"] = str(ip_obj)
        v["length"] = pref_len
        v["comment"] = str(v["comment"]) if "comment" in v else None
        v["max_length"] = ip_obj.max_prefixlen

        if "exact" in v:
            try:
                v["exact"] = ValidatorBool().validate(v["exact"])
            except:
                raise ConfigError(
                    "Invalid 'exact' flag value: {}".format(v["exact"])
                )
        else:
            v["exact"] = False

        def _validate_ge_le(ge_or_le, v, pref_len, ip_obj):
            try:
                v[ge_or_le] = ValidatorUInt().validate(v[ge_or_le])
            except:
                raise ConfigError("Invalid '{}' value ({}): "
                    "must be a positive integer".format(
                    ge_or_le, v[ge_or_le]
                ))

            if v[ge_or_le] < pref_len:
                raise ConfigError(
                    "'{}' ({}) must be greater than or equal to "
                    "the prefix-len ({})".format(
                        ge_or_le, v[ge_or_le], pref_len
                    )
                )
            if v[ge_or_le] > ip_obj.max_prefixlen:
                raise ConfigError(
                    "'{}' ({}) must be less than or equal to "
                    "the max prefix-len ({})".format(
                        ge_or_le, v[ge_or_le], ip_obj.max_prefixlen
                    )
                )

        if "ge" in v and v["ge"]:
            _validate_ge_le("ge", v, pref_len, ip_obj)
        else:
            v["ge"] = None

        if "le" in v and v["le"]:
            _validate_ge_le("le", v, pref_len, ip_obj)
        else:
            v["le"] = None

        if v["ge"] and v["le"]:
            if v["ge"] > v["le"]:
                raise ConfigError(
                    "'ge' must be less than or equal to 'le'"
                )

        if v["ge"] or v["le"]:
            if v["exact"]:
                raise ConfigError(
                    "Can't set 'ge' and 'le' when 'exact' is True"
                )

        return v


class ValidatorBool(ConfigParserValidator):

    def _validate(self, v):
        try:
            if isinstance(v, bool):
                return v
            if isinstance(v, int):
                if v == 0:
                    return False
                elif v == 1:
                    return True
                else:
                    raise ConfigError()
            elif v.lower() in ["true", "yes", "t", "1"]:
                return True
            elif v.lower() in ["false", "no", "f", "0"]:
                return False
            else:
                raise ConfigError()
        except:
            raise ConfigError("Invalid boolean value: {}".format(v))

class ValidatorOption(ConfigParserValidator):

    def __init__(self, name, options, **kwargs):
        ConfigParserValidator.__init__(self, **kwargs)
        self.name = name
        self.options = options

    def _validate(self, v):
        if v is None and None in self.options:
            return v
        if v in self.options:
            return v
        raise ConfigError(
            "Invalid option for '{}': '{}'; "
            "it must be one of {}".format(
                self.name, v,
                ", ".join(["null" if o is None else "'{}'".format(o)
                           for o in self.options])
            )
        )

class ValidatorIPMinMaxLen(ConfigParserValidator):

    def __init__(self, ver, **kwargs):
        ConfigParserValidator.__init__(self, **kwargs)
        self.ver = ver

    def _validate(self, v):
        if not isinstance(v, dict):
            raise ConfigError(
                "Invalid format for IPv{} min/max length".format(self.ver)
            )

        if self.ver == 4:
            max_val = 32
        else:
            max_val = 128

        for min_max in ("min", "max"):
            if min_max not in v:
                raise ConfigError(
                    "Missing '{}' in the IPv{} min/max length".format(
                        min_max, self.ver
                    )
                )
            try:
                val = ValidatorUInt().validate(v[min_max])
            except ConfigError:
                raise ConfigError(
                    "Invalid '{}' in the IPv{} min/max length: {}".format(
                        min_max, self.ver, v[min_max]
                    )
                )
        
            if val > max_val:
                raise ConfigError(
                    "Value of '{}' in the IPv{} min/max length out of "
                    "range; given {}, allowed: {}-{}".format(
                        min_max, self.ver, val, 0, max_val
                    )
                )

        if int(v["min"]) > int(v["max"]):
            raise ConfigError(
                "In the IPv{} min/max length, the value of 'min' must be "
                "<= the value of 'max'".format(self.ver)
            )
        return {
            "min": int(v["min"]),
            "max": int(v["max"])
        }

class ValidatorMaxASPathLen(ConfigParserValidator):

    def _validate(self, v):
        try:
            val = ValidatorUInt().validate(v)
            if val >= 1 and val <= 64:
                return int(v)
            else:
                raise ConfigError()
        except ConfigError:
            raise ConfigError(
                "Invalid max_as_path_len: must be an integer "
                "between 1 and 64"
            )

class ValidatorCommunity(ConfigParserValidator):

    EXPECTED_PARTS_CNT = None

    def __init__(self, rs_as, **kwargs):
        ConfigParserValidator.__init__(self, **kwargs)
        self.rs_as = rs_as
        self.peer_as_macro_needed = kwargs.get("peer_as_macro_needed", False)

    def _expand_rs_as_macro(self, v):
        if "rs_as" in v:
            if self.rs_as:
                return v.replace("rs_as", str(self.rs_as))
            else:
                raise ConfigError(
                    "Can't expand 'rs_as' macro in {}: "
                    "'rs_as' unknown".format(v)
                )
        else:
            return v

    def _get_parts(self, val):
        parts = map(str.strip, val.split(":"))
        if len(parts) != self.EXPECTED_PARTS_CNT:
            raise ConfigError()

        # peer_as macro usage checks
        peer_as_macro_found = False
        for part_idx in range(len(parts)):
            if parts[part_idx] != "peer_as":
                continue
            if self.peer_as_macro_needed:
                peer_as_macro_found = True
                if part_idx != len(parts) - 1:
                    # peer_as macro allowed only in the last part
                    raise ConfigError("'peer_as' macro can be used only "
                                      "in the last part of the value")
            else:
                raise ConfigError("'peer_as' macro not allowed")
        if self.peer_as_macro_needed and not peer_as_macro_found:
            raise ConfigError("'peer_as' macro is mandatory in this "
                              "community")
        return parts

class ValidatorCommunityStd(ValidatorCommunity):

    EXPECTED_PARTS_CNT = 2

    def _validate(self, v):
        val = self._expand_rs_as_macro(v)

        try:
            validated_parts = []
            parts = self._get_parts(val)
            for part in parts:
                if part.strip() == "peer_as":
                    validated_parts.append("peer_as")
                    continue
                part_val = ValidatorUInt().validate(part)
                if part_val < 0 or part_val > 65535:
                    raise ConfigError()
                validated_parts.append(str(int(part_val)))
            return ":".join(validated_parts)
        except ConfigError as e:
            raise ConfigError(
                "Invalid BGP standard community: {}{}; "
                "it must be in the x:x format, with x = a 16-bit "
                "unsigned integer; the 'rs_as' macro "
                "can be used to represent the route "
                "server's ASN provided "
                "that it is a 16-bit ASN".format(
                    v, " - {}".format(str(e)) if str(e) else ""
                )
            )

class ValidatorCommunityLrg(ValidatorCommunity):

    EXPECTED_PARTS_CNT = 3

    def _validate(self, v):
        val = self._expand_rs_as_macro(v)

        try:
            validated_parts = []
            parts = self._get_parts(val)
            for part in parts:
                if part.strip() == "peer_as":
                    validated_parts.append("peer_as")
                    continue
                part_val = ValidatorUInt().validate(part)
                if part_val < 0 or part_val > 4294967295:
                    raise ConfigError()
                validated_parts.append(str(int(part_val)))
            return ":".join(validated_parts)
        except ConfigError as e:
            raise ConfigError(
                "Invalid BGP large community: {}{}; "
                "it must be in the x:x:x format, with x = a 32-bit "
                "unsigned integer; the 'rs_as' and 'peer-as' macros "
                "can be used to represent, respectively, the route "
                "server's ASN and the destination peer's ASN".format(
                    v, " - {}".format(str(e)) if str(e) else ""
                )
            )

class ValidatorCommunityExt(ValidatorCommunity):

    EXPECTED_PARTS_CNT = 3

    def _validate(self, v):
        val = self._expand_rs_as_macro(v)

        # TODO: should be improved
        try:
            validated_parts = []
            parts = self._get_parts(val)
            if parts[0].strip().lower() not in ("rt", "ro"):
                raise ConfigError()
            validated_parts.append(parts[0].strip().lower())
            for part in parts[1:]:
                if part.strip() == "peer_as":
                    validated_parts.append("peer_as")
                    continue
                part_val = ValidatorUInt().validate(part)
                if part_val < 0 or part_val > 4294967295:
                    raise ConfigError()
                validated_parts.append(str(int(part_val)))
            return ":".join(validated_parts)
        except ConfigError as e:
            raise ConfigError(
                "Invalid BGP extended community: {}{}; "
                "it must be in the k:x:x format, with k one of "
                "'rt' or 'ro' and x = an unsigned integer; "
                "the 'rs_as' and 'peer-as' macros "
                "can be used to represent, respectively, the route "
                "server's ASN and the destination peer's ASN".format(
                    v, " - {}".format(str(e)) if str(e) else ""
                )
            )

