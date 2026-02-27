import json
import random
import pandas as pd
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from rest_framework.decorators import api_view
from django.conf import settings
import os


@api_view(["GET"])
def platform_data_status(request):
    try:
        file_path = os.path.join(settings.BASE_DIR, "reports", "dummy_data.json")

        with open(file_path, "r") as f:
            all_data = json.load(f)

        response_data = {}

        for platform, data in all_data.items():

            randomized_data = []

            for row in data:
                new_row = row.copy()
                new_row["likes"] += random.randint(-50, 100)
                new_row["comments"] += random.randint(-10, 30)
                new_row["shares"] += random.randint(-5, 20)
                new_row["engagement_rate"] = round(
                    row["engagement_rate"] + random.uniform(-1, 1), 2
                )
                randomized_data.append(new_row)

            random.shuffle(randomized_data)

            response_data[platform.lower()] = {
                "status": "Completed",
                "count": len(randomized_data),
            }

        return JsonResponse(response_data)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(["GET"])
def export_report(request, platform, file_type):
    try:
        file_path = os.path.join(settings.BASE_DIR, "reports", "dummy_data.json")

        with open(file_path, "r") as f:
            all_data = json.load(f)

        platform = platform.lower()

        if platform not in all_data:
            return HttpResponse("Invalid platform", status=400)

        data = all_data[platform]

        randomized_data = []
        for row in data:
            new_row = row.copy()
            new_row["likes"] += random.randint(-50, 100)
            new_row["comments"] += random.randint(-10, 30)
            new_row["shares"] += random.randint(-5, 20)
            new_row["engagement_rate"] = round(
                row["engagement_rate"] + random.uniform(-1, 1), 2
            )
            randomized_data.append(new_row)

        random.shuffle(randomized_data)

        df = pd.DataFrame(randomized_data)

        if file_type == "json":
            response = HttpResponse(
                json.dumps(randomized_data),
                content_type="application/json",
            )
            response["Content-Disposition"] = f"attachment; filename={platform}.json"
            return response

        elif file_type == "csv":
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = f"attachment; filename={platform}.csv"
            df.to_csv(response, index=False)
            return response

        elif file_type == "excel":
            response = HttpResponse(
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            response["Content-Disposition"] = f"attachment; filename={platform}.xlsx"
            df.to_excel(response, index=False)
            return response

        return HttpResponse("Invalid type", status=400)

    except Exception as e:
        return HttpResponse(str(e), status=500)