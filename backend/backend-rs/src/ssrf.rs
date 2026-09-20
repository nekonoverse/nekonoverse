//! `app/utils/network.py` の `_is_blocked_ip`/`is_private_host` を移植したもの。
//!
//! IPv4/IPv6 の CIDR 表は Python 3.12 の `ipaddress._IPv4Constants`/
//! `_IPv6Constants` (IANA special-purpose registry 準拠) と文字列レベルで
//! 完全一致させている。1レンジでも取りこぼすと SSRF 保護の穴になるため、
//! 手計算でのビット演算ミスを避けて Python 側のネットワーク表記
//! (`"10.0.0.0/8"` 等) をそのまま文字列としてコピーし実行時にパースしている。

use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};
use std::sync::LazyLock;

fn v4_net(s: &str) -> (Ipv4Addr, u8) {
    let (addr, prefix) = s.split_once('/').expect("static CIDR literal");
    (
        addr.parse().expect("static CIDR literal"),
        prefix.parse().expect("static CIDR literal"),
    )
}

fn v6_net(s: &str) -> (Ipv6Addr, u8) {
    let (addr, prefix) = s.split_once('/').expect("static CIDR literal");
    (
        addr.parse().expect("static CIDR literal"),
        prefix.parse().expect("static CIDR literal"),
    )
}

fn v4_mask(prefix: u8) -> u32 {
    if prefix == 0 {
        0
    } else {
        u32::MAX << (32 - prefix)
    }
}

fn v4_in_network(ip: u32, network: Ipv4Addr, prefix: u8) -> bool {
    let mask = v4_mask(prefix);
    (ip & mask) == (u32::from(network) & mask)
}

fn v6_mask(prefix: u8) -> u128 {
    if prefix == 0 {
        0
    } else {
        u128::MAX << (128 - prefix)
    }
}

fn v6_in_network(ip: u128, network: Ipv6Addr, prefix: u8) -> bool {
    let mask = v6_mask(prefix);
    (ip & mask) == (u128::from(network) & mask)
}

// `ipaddress._IPv4Constants._private_networks` (python 3.12) と同一。
static V4_PRIVATE_NETS: LazyLock<Vec<(Ipv4Addr, u8)>> = LazyLock::new(|| {
    [
        "0.0.0.0/8",
        "10.0.0.0/8",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.0.170/31",
        "192.0.2.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "240.0.0.0/4",
        "255.255.255.255/32",
    ]
    .iter()
    .map(|s| v4_net(s))
    .collect()
});

// `ipaddress._IPv4Constants._private_networks_exceptions` と同一。
static V4_PRIVATE_EXCEPTIONS: LazyLock<Vec<(Ipv4Addr, u8)>> = LazyLock::new(|| {
    ["192.0.0.9/32", "192.0.0.10/32"]
        .iter()
        .map(|s| v4_net(s))
        .collect()
});

const V4_LOOPBACK: &str = "127.0.0.0/8";
const V4_LINKLOCAL: &str = "169.254.0.0/16";
const V4_MULTICAST: &str = "224.0.0.0/4";
const V4_RESERVED: &str = "240.0.0.0/4";

fn v4_is_blocked(ip: Ipv4Addr) -> bool {
    let raw = u32::from(ip);
    let is_private = V4_PRIVATE_NETS
        .iter()
        .any(|&(n, p)| v4_in_network(raw, n, p))
        && !V4_PRIVATE_EXCEPTIONS
            .iter()
            .any(|&(n, p)| v4_in_network(raw, n, p));
    let (lb_n, lb_p) = v4_net(V4_LOOPBACK);
    let (ll_n, ll_p) = v4_net(V4_LINKLOCAL);
    let (mc_n, mc_p) = v4_net(V4_MULTICAST);
    let (rv_n, rv_p) = v4_net(V4_RESERVED);
    is_private
        || v4_in_network(raw, lb_n, lb_p)
        || v4_in_network(raw, rv_n, rv_p)
        || v4_in_network(raw, ll_n, ll_p)
        || v4_in_network(raw, mc_n, mc_p)
        || ip.is_unspecified()
}

// `ipaddress._IPv6Constants._private_networks` と同一。
static V6_PRIVATE_NETS: LazyLock<Vec<(Ipv6Addr, u8)>> = LazyLock::new(|| {
    [
        "::1/128",
        "::/128",
        "::ffff:0:0/96",
        "64:ff9b:1::/48",
        "100::/64",
        "2001::/23",
        "2001:db8::/32",
        "2002::/16",
        "3fff::/20",
        "fc00::/7",
        "fe80::/10",
    ]
    .iter()
    .map(|s| v6_net(s))
    .collect()
});

// `ipaddress._IPv6Constants._private_networks_exceptions` と同一。
static V6_PRIVATE_EXCEPTIONS: LazyLock<Vec<(Ipv6Addr, u8)>> = LazyLock::new(|| {
    [
        "2001:1::1/128",
        "2001:1::2/128",
        "2001:3::/32",
        "2001:4:112::/48",
        "2001:20::/28",
        "2001:30::/28",
    ]
    .iter()
    .map(|s| v6_net(s))
    .collect()
});

// `ipaddress._IPv6Constants._reserved_networks` と同一。
static V6_RESERVED_NETS: LazyLock<Vec<(Ipv6Addr, u8)>> = LazyLock::new(|| {
    [
        "::/8", "100::/8", "200::/7", "400::/6", "800::/5", "1000::/4", "4000::/3", "6000::/3",
        "8000::/3", "a000::/3", "c000::/3", "e000::/4", "f000::/5", "f800::/6", "fe00::/9",
    ]
    .iter()
    .map(|s| v6_net(s))
    .collect()
});

const V6_LINKLOCAL: &str = "fe80::/10";
const V6_MULTICAST: &str = "ff00::/8";

fn v6_is_blocked(ip: Ipv6Addr) -> bool {
    let raw = u128::from(ip);
    let is_private = V6_PRIVATE_NETS
        .iter()
        .any(|&(n, p)| v6_in_network(raw, n, p))
        && !V6_PRIVATE_EXCEPTIONS
            .iter()
            .any(|&(n, p)| v6_in_network(raw, n, p));
    let (ll_n, ll_p) = v6_net(V6_LINKLOCAL);
    let (mc_n, mc_p) = v6_net(V6_MULTICAST);
    is_private
        || ip.is_loopback()
        || V6_RESERVED_NETS
            .iter()
            .any(|&(n, p)| v6_in_network(raw, n, p))
        || v6_in_network(raw, ll_n, ll_p)
        || v6_in_network(raw, mc_n, mc_p)
        || ip.is_unspecified()
}

/// `app.utils.network._is_blocked_ip` を移植したもの。IPv4 射影 IPv6 アドレスは
/// 埋め込まれた IPv4 アドレスとして判定する (`Ipv6Addr::to_ipv4_mapped` が
/// Python の `IPv6Address.ipv4_mapped` と同じ `::ffff:0:0/96` 判定をする)。
pub fn is_blocked_ip(addr: IpAddr) -> bool {
    match addr {
        IpAddr::V4(v4) => v4_is_blocked(v4),
        IpAddr::V6(v6) => match v6.to_ipv4_mapped() {
            Some(v4) => v4_is_blocked(v4),
            None => v6_is_blocked(v6),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Python 3.12 の `ipaddress` を使って生成したオラクル値との突き合わせ。
    /// (`_is_blocked_ip` と同一ロジックを Python 側で実行して得た期待値)
    #[test]
    fn matches_python_oracle() {
        let cases: &[(&str, bool)] = &[
            ("8.8.8.8", false),
            ("1.1.1.1", false),
            ("127.0.0.1", true),
            ("127.255.255.255", true),
            ("10.0.0.1", true),
            ("10.255.255.255", true),
            ("172.16.0.1", true),
            ("172.31.255.255", true),
            ("172.15.255.255", false),
            ("172.32.0.0", false),
            ("192.168.1.1", true),
            ("192.168.255.255", true),
            ("169.254.169.254", true),
            ("169.254.0.1", true),
            ("0.0.0.0", true),
            ("0.255.255.255", true),
            ("1.0.0.0", false),
            ("192.0.0.1", true),
            ("192.0.0.9", false),
            ("192.0.0.10", false),
            ("192.0.0.170", true),
            ("192.0.0.171", true),
            ("192.0.0.172", true),
            ("192.0.2.1", true),
            ("198.18.0.1", true),
            ("198.19.255.255", true),
            ("198.20.0.0", false),
            ("198.51.100.5", true),
            ("203.0.113.5", true),
            ("240.0.0.1", true),
            ("255.255.255.255", true),
            ("224.0.0.1", true),
            ("239.255.255.255", true),
            ("223.255.255.255", false),
            ("100.64.0.1", false),
            ("100.127.255.255", false),
            ("100.63.255.255", false),
            ("100.128.0.0", false),
            ("::1", true),
            ("::", true),
            ("fe80::1", true),
            ("fc00::1", true),
            ("fd12:3456:789a:1::1", true),
            ("ff02::1", true),
            ("2001:db8::1", true),
            ("2606:4700:4700::1111", false),
            ("2001:4860:4860::8888", false),
            ("::ffff:127.0.0.1", true),
            ("::ffff:8.8.8.8", false),
            ("::ffff:169.254.169.254", true),
            ("64:ff9b:1::1", true),
            ("2001:1::1", false),
            ("2001:1::2", false),
            ("2001:1::3", true),
            ("2001:3::1", false),
            ("2001:20::1", false),
            ("2001:30::1", false),
            ("100::1", true),
            ("3fff::1", true),
            ("2002::1", true),
            ("2001:4:112::1", false),
        ];

        for &(ip_str, expected) in cases {
            let addr: IpAddr = ip_str.parse().unwrap();
            assert_eq!(is_blocked_ip(addr), expected, "ip={ip_str}");
        }
    }
}
