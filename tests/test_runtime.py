import pytest

from django_showcase.runtime.database import scenario_runtime, scenario_transaction
from django_showcase.seed.executor import SeedExecutor
from django_showcase.seed.plan import ModelSeed, SeedPlan
from tests.shop.models import Customer, Order


@pytest.mark.django_db
def test_seed_creates_demo_data_and_rolls_back():
    with scenario_runtime(enabled=True) as session:
        executor = SeedExecutor(session)
        with scenario_transaction(session):
            result = executor.execute(
                SeedPlan(
                    models=[
                        ModelSeed(
                            model="shop.Order", count=3, fields={"status": "pending"}
                        )
                    ]
                )
            )
            assert result.objects_created == 3
            assert Order.objects.filter(status="pending").count() == 3
            assert Customer.objects.count() == 1
            assert Order.objects.first().customer.name == "Demo name"

        assert Order.objects.count() == 0
        assert Customer.objects.count() == 0


@pytest.mark.django_db
def test_read_only_session_never_writes():
    with scenario_runtime(enabled=False) as session:
        result = SeedExecutor(session).execute(
            SeedPlan(models=[ModelSeed(model="shop.Order", count=5)])
        )

    assert result.skipped
    assert result.objects_created == 0
    assert Order.objects.count() == 0
