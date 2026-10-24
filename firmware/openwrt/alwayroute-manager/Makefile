include $(TOPDIR)/rules.mk

PKG_NAME:=alwayroute-manager
PKG_VERSION:=1.0.0
PKG_RELEASE:=11
PKG_LICENSE:=MIT GPL-3.0-only
PKGARCH:=all
ROUTING_INPUT:=$(TOPDIR)/alwayroute-input/routing
PKG_FILE_DEPENDS:=$(ROUTING_INPUT)/domestic-domain.srs $(ROUTING_INPUT)/domestic-ip.srs $(ROUTING_INPUT)/manifest.json $(ROUTING_INPUT)/LICENSE

include $(INCLUDE_DIR)/package.mk

# package.mk tracks the owned policies; PKG_FILE_DEPENDS tracks compiled data.

define Package/alwayroute-manager
  SECTION:=net
  CATEGORY:=Network
  TITLE:=AlwayRoute transactional configuration manager
  DEPENDS:=+alwayroute-core +alwayroute-forwarding +rpcd-mod-ucode +ucode +ucode-mod-fs +ucode-mod-digest +uclient-fetch +ca-bundle
endef

define Package/alwayroute-manager/conffiles
/etc/alwayroute/
endef

define Build/Prepare
	$(INSTALL_DIR) $(PKG_BUILD_DIR)/routing
	$(CP) $(ROUTING_INPUT)/domestic-domain.srs $(ROUTING_INPUT)/domestic-ip.srs $(ROUTING_INPUT)/manifest.json $(ROUTING_INPUT)/LICENSE $(PKG_BUILD_DIR)/routing/
endef

define Build/Compile
endef

define Package/alwayroute-manager/install
	$(INSTALL_DIR) $(1)/usr/share/ucode/alwayroute $(1)/usr/share/rpcd/ucode $(1)/usr/share/rpcd/acl.d $(1)/usr/libexec $(1)/etc/init.d $(1)/etc/uci-defaults
	$(INSTALL_DIR) $(1)/usr/share/alwayroute/policies
	$(INSTALL_DATA) ./files/usr/share/alwayroute/policies/*.json $(1)/usr/share/alwayroute/policies/
	$(INSTALL_DIR) $(1)/usr/share/alwayroute/rules
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/routing/* $(1)/usr/share/alwayroute/rules/
	$(INSTALL_DATA) ./files/usr/share/ucode/alwayroute/*.uc $(1)/usr/share/ucode/alwayroute/
	$(INSTALL_DATA) ./files/usr/share/rpcd/ucode/alwayroute $(1)/usr/share/rpcd/ucode/
	$(INSTALL_DATA) ./files/usr/share/rpcd/acl.d/alwayroute.json $(1)/usr/share/rpcd/acl.d/
	$(INSTALL_BIN) ./files/usr/libexec/alwayroute-* $(1)/usr/libexec/
	$(INSTALL_BIN) ./files/etc/init.d/alwayroute $(1)/etc/init.d/
	$(INSTALL_BIN) ./files/etc/uci-defaults/95-alwayroute-schedule $(1)/etc/uci-defaults/
endef

$(eval $(call BuildPackage,alwayroute-manager))
