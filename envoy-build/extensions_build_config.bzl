EXTENSIONS = {
    "envoy.access_loggers.file": "//source/extensions/access_loggers/file:config",
    "envoy.access_loggers.stderr": "//source/extensions/access_loggers/stream:config",
    "envoy.access_loggers.stdout": "//source/extensions/access_loggers/stream:config",
    "envoy.clusters.dynamic_modules": "//source/extensions/clusters/dynamic_modules:cluster",
    "envoy.clusters.static": "//source/extensions/clusters/static:static_cluster_lib",
    "envoy.config_mux.sotw_grpc_mux_factory": "//source/extensions/config_subscription/grpc/xds_mux:grpc_mux_lib",
    "envoy.config_subscription.grpc": "//source/extensions/config_subscription/grpc:grpc_subscription_lib",
    "envoy.filters.http.dynamic_modules": "//source/extensions/filters/http/dynamic_modules:factory_registration",
    "envoy.filters.http.router": "//source/extensions/filters/http/router:config",
    "envoy.filters.listener.dynamic_modules": "//source/extensions/filters/listener/dynamic_modules:config",
    "envoy.filters.network.dynamic_modules": "//source/extensions/filters/network/dynamic_modules:config",
    "envoy.filters.network.http_connection_manager": "//source/extensions/filters/network/http_connection_manager:config",
    "envoy.http.header_validators.envoy_default": "//source/extensions/http/header_validators/envoy_default:config",
    "envoy.network.dns_resolver.apple": "//source/extensions/network/dns_resolver/apple:config",
    "envoy.network.dns_resolver.cares": "//source/extensions/network/dns_resolver/cares:config",
    "envoy.stat_sinks.dynamic_modules": "//source/extensions/stat_sinks/dynamic_modules:config",
    "envoy.transport_sockets.raw_buffer": "//source/extensions/transport_sockets/raw_buffer:config",
    "envoy.upstreams.http.http": "//source/extensions/upstreams/http/http:config",
}

EXTENSION_CONFIG_VISIBILITY = ["//:extension_config", "//:contrib_library", "//:mobile_library"]

EXTENSION_PACKAGE_VISIBILITY = ["//:extension_library", "//:contrib_library", "//:mobile_library"]

CONTRIB_EXTENSION_PACKAGE_VISIBILITY = ["//:contrib_library"]

MOBILE_PACKAGE_VISIBILITY = ["//:mobile_library"]

LEGACY_ALWAYSLINK = 1
