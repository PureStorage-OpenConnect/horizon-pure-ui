
import purestorage


class FlashArrayAPI(object):
    def __init__(self):
        # TODO: Get this info from the horizon config file?
        self.array = purestorage.FlashArray('cinder-fa1.dev.purestorage.com', username='pureuser', password='pureuser')

    def get_volume_stats(self, volume):
        # TODO: Lookup volume and get perf and capacity info for it
        return {}

    def get_host_stats(self, host):
        # TODO: Lookup the purity host and return perf info and connected volumes
        return {}

    def get_array_info(self):
        return self.array.get()
