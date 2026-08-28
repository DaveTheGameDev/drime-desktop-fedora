SPEC    := drime-desktop.spec
NAME    := drime-desktop
VERSION := $(shell rpmspec -q --qf '%{version}\n' $(SPEC) 2>/dev/null | head -1)
TOPDIR  := $(CURDIR)/build
# e.g. make rpm RPMBUILD_OPTS=--nodeps when python3-devel is not installed
RPMBUILD_OPTS ?=

.PHONY: version tarball srpm rpm lint install-local release clean

version:
	@echo $(VERSION)

tarball:
	mkdir -p $(TOPDIR)/SOURCES
	git ls-files -co --exclude-standard | tar -czf $(TOPDIR)/SOURCES/$(NAME)-$(VERSION).tar.gz \
	    --transform 's,^,$(NAME)-$(VERSION)/,' --no-recursion -T -

srpm: tarball
	rpmbuild -bs $(RPMBUILD_OPTS) --define "_topdir $(TOPDIR)" $(SPEC)

rpm: tarball
	rpmbuild -ba $(RPMBUILD_OPTS) --define "_topdir $(TOPDIR)" $(SPEC)

lint:
	rpmlint -r $(NAME).rpmlintrc $(SPEC) $(TOPDIR)/RPMS/noarch/*.rpm || true
	rpm -qpl $(TOPDIR)/RPMS/noarch/*.rpm

install-local:
	sudo dnf install -y $(TOPDIR)/RPMS/noarch/$(NAME)-$(VERSION)-*.noarch.rpm

# Manual release (when not using the GitHub Actions workflow): builds the RPM and
# publishes it with the standard "which file do I download?" header. Pass extra
# notes with NOTES="- fixed X". The tag v$(VERSION) must already be pushed.
release: rpm
	scripts/release-notes.sh $(VERSION) $(notdir $(wildcard build/RPMS/noarch/*.rpm)) > build/release-notes.md
	gh release create v$(VERSION) build/RPMS/noarch/*.rpm build/SRPMS/*.src.rpm build/SOURCES/*.tar.gz \
	    --title v$(VERSION) --notes-file build/release-notes.md

clean:
	rm -rf $(TOPDIR)
