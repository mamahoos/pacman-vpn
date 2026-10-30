var REG_NONE = NewRegistrar("none");
var CLOUDFLARE = NewDnsProvider("cloudflare");
var CF_PROXY_ON = { cloudflare_proxy: "on" };
var CF_PROXY_OFF = { cloudflare_proxy: "off" };

// The origin IP is stamped here by .github/workflows/dns.yml on every sync
// (ssh -> ifconfig.me on the deploy host), never committed as a literal.
D("mamahoos.ir", REG_NONE, DnsProvider(CLOUDFLARE), NO_PURGE,
  // Pacman-vpn public hosts. NO_PURGE keeps records managed by other configs
  // for this zone (e.g. the portfolio repo) untouched; orange-cloud so CF
  // fronts the origin and scripts/check_cloudflare.py stays green.
  A("admin", "__ORIGIN_IP__", TTL(1), CF_PROXY_ON),
  A("sub", "__ORIGIN_IP__", TTL(1), CF_PROXY_ON),
  A("edge", "__ORIGIN_IP__", TTL(1), CF_PROXY_ON),
  // TCP+TLS subscription flavour: grey-cloud on purpose. The client must
  // reach the origin directly because Cloudflare's HTTP proxy cannot carry
  // raw TLS routed by SNI; the Traefik TCP router owns this name.
  A("files", "__ORIGIN_IP__", TTL(1), CF_PROXY_OFF),
);
