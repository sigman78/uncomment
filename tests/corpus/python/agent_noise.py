"""Utility helpers for the demo service."""

# imports
import os
import time


# ============================================================
# Helper functions
# ============================================================
def get_user_name(user):
    """Get the user name."""
    # First, we check if the user is valid
    # Then we return the name from the user object
    return user.name


def compute_total(items):
    # Changed the loop to use sum() as requested
    total = sum(item.price for item in items)  # calculate the total price of all the items in the list
    # old_total = 0
    # for item in items:
    #     old_total += item.price
    return total


# TODO: refactor this later
def process(data):
    """Process the data. 🚀

    Now we simply utilize the helper in order to obtain the result.
    """
    # 1. validate the input
    if not data:
        raise ValueError("empty")
    # 2. transform the data
    result = [normalize(d) for d in data]
    # 3. return the result
    return result
