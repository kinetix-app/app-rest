"""Account photo failures, independent of HTTP transport."""


class PictureMissing(Exception):
    pass


class PictureTooLarge(Exception):
    pass


class UnsupportedPicture(Exception):
    pass


class InvalidPicture(Exception):
    pass


class PictureStorageUnavailable(Exception):
    pass
